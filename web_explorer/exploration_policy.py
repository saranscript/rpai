from __future__ import annotations

"""Algorithm 2 – the main exploration driver for Web-Explorer."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import os, shutil
import json
import networkx as nx
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from playwright_custom.browser.local_playwright_browser import LocalPlaywrightBrowser
from playwright_custom.playwright_controller import PlaywrightController

from .knowledge import AppKnowledge, AbstractAction, ExplorationFlag
from .knowledge_maintenance import KnowledgeMaintainer
from .action_selector import ActionSelector
from .path_finder import PathFinder
from .state_matcher import StateMatcher
from .input_generator import InputTextGenerator

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class ExplorationAgent:
    """High-level orchestrator implementing the exploration loop."""

    def __init__(
        self,
        start_url: str,
        headless: bool = True,
        output_dir: str = "run_artifacts",
        max_depth: int = 5,
        max_steps: int = 100,
        state_sleep: float = 2.0,
        animate_actions: bool = False,
    ) -> None:
        self.start_url = start_url
        self._browser_wrapper = LocalPlaywrightBrowser(headless=headless)
        # create domain allowlist
        self._origin = urlparse(start_url).netloc

        async def _validator(url: str):
            allow = urlparse(url).netloc == self._origin or urlparse(url).netloc == ""
            return ("blocked" if not allow else "ok", allow)

        self._controller = PlaywrightController(
            url_validation_callback=_validator,
            animate_actions=animate_actions,
            sleep_after_action=state_sleep,
        )
        self._output_dir = output_dir
        self._max_depth = max_depth
        self._max_steps = max_steps
        self._state_sleep = state_sleep

        if os.path.exists(self._output_dir):
            shutil.rmtree(self._output_dir)
        os.makedirs(self._output_dir, exist_ok=True)

        # Knowledge related components
        self._knowledge = AppKnowledge()
        self._maintainer = KnowledgeMaintainer(StateMatcher())
        self._selector = ActionSelector()
        self._path_finder = PathFinder()
        self._input_gen = InputTextGenerator()

        # progress tracking
        self._visited_state_ids: set[str] = set()
        self._steps_executed: int = 0
        self._no_path_counter: int = 0
        self._no_path_limit: int = 20
        self._all_elements: dict[str, Any] = {}
        self._sig_cache: dict[str, dict[str, Any]] = {}
        # back-tracking support ------------------------------------------------
        self._state_stack: list[str] = []

    # ------------------------------------------------------------------
    async def explore(self) -> AppKnowledge:
        """Entry-point of the algorithm."""

        async with self._browser_wrapper as bw:  # type: ignore
            context: BrowserContext = self._browser_wrapper.browser_context  # type: ignore
            page: Page = await context.new_page()
            await page.goto(self.start_url)
            await asyncio.sleep(1)
            await page.wait_for_load_state("load")

            # Initial state snapshot and knowledge
            state_snapshot = await self._get_state_snapshot(page)
            self._knowledge = self._maintainer.update_knowledge(
                self._knowledge, None, None, state_snapshot
            )
            current_abs_state_id = self._get_matching_abs_state_id(state_snapshot)
            logger.debug("Initial state: %s (%s)", current_abs_state_id, page.url)

            nav_steps: List[AbstractAction] = []

            while self._should_continue():
                # 1. Determine next action -----------------------------------
                if nav_steps:
                    next_action = nav_steps.pop(0)
                else:
                    # determine next action (prefer local) -----------------
                    next_action = self._selector.select_action(
                        self._knowledge, current_abs_state_id
                    )
                    # Skip actions that are definitely external links --------------------
                    while next_action and next_action.actual_elements and \
                          await self._would_navigate_external(page, next_action.actual_elements[0].node_id):
                        logger.info("Pre-filter: action %s is external – marking ineffective", next_action.action_id)
                        self._knowledge.update_action_flag(next_action, ExplorationFlag.INEFFECTIVE)
                        next_action = self._selector.select_action(self._knowledge, current_abs_state_id)
                    if next_action is None:
                        logger.info("All actions explored.")
                        break
                    # If target element not present, compute nav path
                    if not await self._is_action_available(page, next_action):
                        current_state = self._knowledge.abstract_states[current_abs_state_id]
                        # Log our state stack for debugging
                        logger.debug("Current URL: %s | State: %s | Stack: %s", 
                                   page.url, current_abs_state_id, self._state_stack)
                        # push current state for back-tracking if it still has work
                        if any(a.exploration_flag == ExplorationFlag.UNEXPLORED for a in current_state.actions.values()):
                            if current_abs_state_id not in self._state_stack:
                                logger.debug("Pushing state %s to stack (Url: %s)", current_abs_state_id, page.url)
                                self._state_stack.append(current_abs_state_id)
                        nav_steps = self._path_finder.find_path(
                            self._knowledge, current_state, next_action
                        )
                        if not nav_steps:
                            logger.warning("No navigation path found – marking action ineffective.")
                            self._knowledge.update_action_flag(next_action, ExplorationFlag.INEFFECTIVE)
                            self._no_path_counter += 1
                            continue  # pick another action without restarting app
                        next_action = nav_steps.pop(0)
                    else:
                        self._no_path_counter = 0  # reset when successful

                # 2. Execute action -----------------------------------------
                concrete_action_info = await self._execute_action(page, next_action)

                # 3. Observe new state & update knowledge -------------------
                await page.wait_for_timeout(self._state_sleep * 1000)
                new_state_snapshot = await self._get_state_snapshot(page)
                
                # First update knowledge with cached grouped actions
                self._knowledge = self._maintainer.update_knowledge(
                    self._knowledge,
                    prev_state_snapshot=state_snapshot,
                    prev_action_concrete=concrete_action_info,
                    new_state_snapshot=new_state_snapshot,
                )
                state_snapshot = new_state_snapshot

                # refresh current abstract state id after state transition
                current_abs_state_id = self._get_matching_abs_state_id(state_snapshot)

                # update progress trackers
                self._visited_state_ids.add(current_abs_state_id)
                self._steps_executed += 1

                # If we are in navigation mode (nav_steps not empty) but new state no longer matches
                if nav_steps:
                    expected_state = nav_steps[0].source_abs_state  # we want to reach target of path
                    current_state_obj = self._knowledge.abstract_states[current_abs_state_id]
                    if expected_state != current_state_obj:
                        # Recompute navigate path (Algorithm 2 – UpdateNavigatePath)
                        nav_steps = self._path_finder.find_path(
                            self._knowledge, current_state_obj, nav_steps[-1]
                        )
                        if not nav_steps:
                            # give up and treat as no path situation
                            self._no_path_counter += 1
                            logger.debug("UpdateNavigatePath failed – increment no_path_counter to %s", self._no_path_counter)
                        else:
                            logger.debug("UpdateNavigatePath succeeded – new path length %s", len(nav_steps))

                # Restart from start URL if too many consecutive no-path situations
                if self._no_path_counter >= self._no_path_limit:
                    logger.warning("Too many navigation-failures – restarting application context")
                    await page.goto(self.start_url, wait_until="load")
                    state_snapshot = await self._get_state_snapshot(page)
                    current_abs_state_id = self._get_matching_abs_state_id(state_snapshot)
                    self._no_path_counter = 0

                # --------------------- Back-tracking ---------------------
                current_state_obj = self._knowledge.abstract_states[current_abs_state_id]
                logger.debug("Checking if state %s is finished. Unexplored: %d, Stack: %s", 
                           current_abs_state_id, 
                           sum(1 for a in current_state_obj.actions.values() if a.exploration_flag == ExplorationFlag.UNEXPLORED),
                           self._state_stack)
                if not any(a.exploration_flag == ExplorationFlag.UNEXPLORED for a in current_state_obj.actions.values()):
                    logger.debug("Current state %s is finished, looking for previous states to return to", current_abs_state_id)
                    # current state finished; try to pop a previous state with remaining work
                    while self._state_stack:
                        target_state_id = self._state_stack.pop()
                        logger.debug("Popped %s from stack", target_state_id)
                        target_state_obj = self._knowledge.abstract_states.get(target_state_id)
                        if target_state_obj and any(a.exploration_flag == ExplorationFlag.UNEXPLORED for a in target_state_obj.actions.values()):
                            nav_steps = self._path_finder.path_to_state(
                                self._knowledge, current_state_obj, target_state_obj
                            )
                            if nav_steps:
                                logger.info("Back-tracking to earlier state %s with %d navigation steps", 
                                          target_state_id, len(nav_steps))
                                break
                            else:
                                logger.warning("Could not find path back to state %s", target_state_id)
                    if not self._state_stack and not nav_steps:
                        logger.debug("Stack empty, no more states to return to")

            # Save final knowledge graph & trace
            with open(os.path.join(self._output_dir, "knowledge.json"), "w", encoding="utf-8") as fh:
                json.dump(self._knowledge.to_json(), fh, indent=2)

            # Prepare sanitized graph for GraphML (remove non-serialisable objects)
            g_raw = self._knowledge.aig.to_networkx()
            g_ml = nx.MultiDiGraph()
            for nid, data in g_raw.nodes(data=True):
                g_ml.add_node(nid)
            for u, v, k, data in g_raw.edges(keys=True, data=True):
                g_ml.add_edge(u, v, key=k)
            try:
                nx.write_graphml(g_ml, os.path.join(self._output_dir, "aig.graphml"))
            except Exception as e:
                logger.warning(f"Failed to write GraphML: {e}")

            # write master elements
            try:
                with open(os.path.join(self._output_dir, "elements_all.json"), "w", encoding="utf-8") as fh:
                    json.dump(self._all_elements, fh, indent=2)
            except Exception as e:
                logger.warning(f"Failed to write elements_all.json: {e}")

            return self._knowledge

    # ------------------------------------------------------------------
    # Helpers -----------------------------------------------------------

    async def _get_state_snapshot(self, page: Page) -> Any:
        """Collect metadata from page and interactive rects for matching."""
        metadata = await self._controller.get_page_metadata(page)
        # save html/screenshot
        html_path = os.path.join(self._output_dir, f"state_{len(self._knowledge.raw_trace)}.html")
        screenshot_path = os.path.join(self._output_dir, f"state_{len(self._knowledge.raw_trace)}.png")
        # Include the URL in metadata for state differentiation
        metadata["url"] = page.url
        
        try:
            content = await page.content()
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            await self._controller.get_screenshot(page, path=screenshot_path)
        except Exception:
            pass
        metadata["html"] = html_path
        interactive_rects = await self._controller.get_interactive_rects(page)
        # compute xpaths ---------------------------------------------------
        xpaths: dict[str, str] = await self._compute_xpaths(page, list(interactive_rects.keys()))
        for eid, info in interactive_rects.items():
            info_with_xpath = dict(info)
            if eid in xpaths:
                info_with_xpath["xpath"] = xpaths[eid]
            interactive_rects[eid] = info_with_xpath

        metadata["interactive_rects"] = {k: dict(v) for k, v in interactive_rects.items()}

        # Debug XPath generation
        logger.debug(f"XPaths computed: {len(xpaths)} out of {len(interactive_rects)} elements")

        # signature for caching
        sig = StateMatcher().signature(metadata)

        if sig in self._sig_cache:
            cached = self._sig_cache[sig]
            grouped_actions = cached["grouped_actions"]
            grouped_json_path = cached["grouped_file"]
            elements_json_path = cached["elements_file"]
            metadata["page_description"] = cached.get("page_desc", "")
            metadata["element_groups"] = cached.get("element_groups", [])
        else:
            # persist per-snapshot element data ---------------------------------
            elements_json_path = os.path.join(self._output_dir, f"elements_{len(self._knowledge.raw_trace)}.json")
            try:
                with open(elements_json_path, "w", encoding="utf-8") as fh:
                    json.dump(metadata["interactive_rects"], fh, indent=2)
            except Exception:
                pass

            from .element_grouper import ElementGrouper
            eg = ElementGrouper()
            grouped_actions, page_desc, element_groups, token_usage = eg.extract_actions(metadata)

            grouped_json_path = os.path.join(self._output_dir, f"grouped_actions_{len(self._knowledge.raw_trace)}.json")
            try:
                with open(grouped_json_path, "w", encoding="utf-8") as fh:
                    json.dump({
                        "grouped_actions": grouped_actions,
                        "page_description": page_desc,
                        "element_groups": element_groups,
                        "token_usage": token_usage,
                    }, fh, indent=2)
            except Exception:
                pass

            # cache it
            self._sig_cache[sig] = {
                "grouped_actions": grouped_actions,
                "grouped_file": grouped_json_path,
                "elements_file": elements_json_path,
                "page_desc": page_desc,
                "element_groups": element_groups,
            }

            # attach LLM outputs to metadata so that KnowledgeMaintainer can persist them
            metadata["page_description"] = page_desc
            metadata["element_groups"] = element_groups
            metadata["token_usage_element_grouper"] = token_usage

        metadata["grouped_actions_file"] = grouped_json_path
        metadata["grouped_actions"] = grouped_actions

        # if element file not yet written (cached) ensure file exists
        if not os.path.exists(elements_json_path):
            try:
                with open(elements_json_path, "w", encoding="utf-8") as fh:
                    json.dump(metadata["interactive_rects"], fh, indent=2)
            except Exception:
                pass

        # update master aggregation
        for eid, meta in metadata["interactive_rects"].items():
            if eid not in self._all_elements:
                self._all_elements[eid] = meta
        return metadata

    def _get_matching_abs_state_id(self, snapshot: Any) -> str:
        st = StateMatcher().match_state(self._knowledge, snapshot)
        assert st, "State should have been inserted into knowledge already"
        return st.state_id

    def _should_continue(self) -> bool:
        """Return True if exploration should proceed based on multiple criteria."""
        if not self._knowledge.unexplored_action_ids:
            return False
        if self._steps_executed >= self._max_steps:
            return False
        if len(self._visited_state_ids) > self._max_depth:
            return False
        return True

    async def _is_action_available(self, page: Page, action: AbstractAction) -> bool:
        if not action.actual_elements:
            return False
        elem = action.actual_elements[0]
        elem_id = elem.node_id
        rects = await self._controller.get_interactive_rects(page)
        if elem_id in rects:
            return True

        # Attempt to locate by XPath and refresh element id ----------------
        target_xpath = elem.description or ""
        if target_xpath:
            for rid, info in rects.items():
                if info.get("xpath") == target_xpath:
                    # Update cached id so future clicks use new value
                    logger.debug("Element id changed – updating from %s to %s", elem_id, rid)
                    elem.node_id = rid
                    return True
        return False

    async def _execute_action(self, page: Page, action: AbstractAction) -> dict:
        """Perform the abstract action concretely on the page and return info."""
        if not action.actual_elements:
            raise RuntimeError("Action has no concrete elements")
        elem_id = action.actual_elements[0].node_id
        
        action_result = {"action_type": action.action_type.value, "element_id": elem_id}
        
        # Early check: ensure element still present on current page
        if action.action_type.value == "click":
            # Pre-check for external links to avoid unnecessary animations
            if await self._would_navigate_external(page, elem_id):
                logger.info("Skipping external link click – outside domain: %s", elem_id)
                self._knowledge.update_action_flag(action, ExplorationFlag.INEFFECTIVE)
                
                # If this action is part of a group, only mark THIS element as ineffective
                # not the whole abstract action
                if len(action.actual_elements) > 1:
                    logger.info("Action has %d elements - only marking individual element as ineffective", 
                              len(action.actual_elements))
                    # Find the next non-explored element in the group
                    for i, element in enumerate(action.actual_elements):
                        if element.node_id != elem_id and await self._is_action_available(page, AbstractAction(
                            action_type=action.action_type,
                            actual_elements=[element]
                        )):
                            # Create a new action instance for the next element
                            logger.info("Will try next element in group: %s", element.node_id)
                            next_elem_action = AbstractAction(
                                action_type=action.action_type,
                                exploration_flag=ExplorationFlag.UNEXPLORED,
                                actual_elements=[element],
                                function_desc=action.function_desc
                            )
                            self._knowledge.register_action(next_elem_action)
                            current_state = self._knowledge.abstract_states[current_abs_state_id] 
                            current_state.actions[next_elem_action.action_id] = next_elem_action
                            break
                return action_result
            
            # Verify element availability on this page
            if not await self._is_action_available(page, action):
                logger.info("Element %s not present in current DOM – marking action ineffective", elem_id)
                self._knowledge.update_action_flag(action, ExplorationFlag.INEFFECTIVE)
                return {"action_type": action.action_type.value, "element_id": elem_id}
        
        # Show marked elements before action if animations are enabled
        if self._controller.animate_actions:
            # Show all marked elements to visualize available interactions
            await self._controller.show_marked_elements(page)
            await asyncio.sleep(1)  # Allow time to see the elements
        
        try:
            if action.action_type.value == "click":
                # Add click effect animation before actual click if animations enabled
                if self._controller.animate_actions:
                    await self._controller.add_action_effect(page, "click", elem_id)
                    await asyncio.sleep(0.5)
                    
                # Perform the click
                await self._controller.click_id(page.context, page, elem_id)
                
            elif action.action_type.value == "input":
                # Add typing effect animation if animations enabled
                if self._controller.animate_actions:
                    await self._controller.add_action_effect(page, "type", elem_id)
                    await asyncio.sleep(0.5)
                    
                # Generate text and fill the input
                text = await self._input_gen.generate(await self._get_state_snapshot(page), {})
                await self._controller.fill_id(page, elem_id, text)
                
                # Remove typing effect
                if self._controller.animate_actions:
                    await self._controller.remove_action_effect(page, "type")
                    
            elif action.action_type.value == "scroll":
                # Add hover effect animation if animations enabled
                if self._controller.animate_actions:
                    await self._controller.add_action_effect(page, "hover", elem_id)
                    await asyncio.sleep(0.5)
                    await self._controller.remove_action_effect(page, "hover")
                    
                await self._controller.scroll_id(page, elem_id, direction="down")
                
            elif action.action_type.value == "long_click":
                # Add click effect animation if animations enabled
                if self._controller.animate_actions:
                    await self._controller.add_action_effect(page, "click", elem_id)
                    await asyncio.sleep(0.5)
                    
                await self._controller.click_id(page.context, page, elem_id, hold=1.0)
            # add more types as needed

            # after performing, attempt to close extra tabs if single-tab mode desired
            await self._ensure_single_tab(page.context)

            # domain enforcement: if navigation changed domain, revert and mark ineffective
            try:
                current_netloc = urlparse(page.url).netloc
                if current_netloc != self._origin and current_netloc != "":
                    logger.warning("Navigated outside allowed domain – reverting and marking action ineffective.")
                    self._knowledge.update_action_flag(action, ExplorationFlag.INEFFECTIVE)
                    try:
                        # Try to go back first
                        await page.go_back(timeout=5000, wait_until="domcontentloaded")
                    except Exception as e:
                        logger.warning(f"Failed to go back: {str(e)}")
                        # If back navigation fails, go to start URL
                        await page.goto(self.start_url, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(f"Error in domain enforcement: {str(e)}")
        finally:
            # Hide marked elements after action if they were shown
            if self._controller.animate_actions:
                await self._controller.hide_marked_elements(page)
                await self._controller.cleanup_animations(page)

        return action_result

    async def _ensure_single_tab(self, context: BrowserContext) -> None:
        """Close background tabs to keep exploration deterministic."""
        pages = context.pages
        # keep first page open
        for p in pages[1:]:
            try:
                await p.close()
            except Exception:
                pass

    async def _compute_xpaths(self, page: Page, element_ids: list[str]) -> dict[str, str]:
        """Return mapping elementId -> absolute xpath string for all DOM elements.
        
        This uses the raw DOM structure for all elements on the page, not just
        interactives with __elementId attributes, since PlaywrightController might
        use other selectors.
        """
        if not element_ids:
            return {}
            
        js = """
        () => {
            // General XPath computation for any element
            function getXPathForElement(element) {
                // If no element or not an element node, return empty string
                if (!element || element.nodeType !== 1) {
                    return '';
                }
                
                // Special cases
                if (element === document.body) {
                    return '/html/body';
                }
                
                // Get all siblings of the same type
                let siblings = Array.from(element.parentNode.childNodes)
                    .filter(node => node.nodeType === 1 && node.tagName === element.tagName);
                
                // Count position among siblings
                let position = 1;
                for (let i = 0; i < siblings.length; i++) {
                    if (siblings[i] === element) {
                        break;
                    }
                    position++;
                }
                
                // Build the path recursively
                return getXPathForElement(element.parentNode) + '/' + 
                       element.tagName.toLowerCase() + '[' + position + ']';
            }
            
            // Track all elements, indexed by the DOM's natural id
            const elementXPaths = {};
            
            // Process all elements on the page
            const allElements = document.querySelectorAll('*');
            for (let i = 0; i < allElements.length; i++) {
                const el = allElements[i];
                
                // Store by both element id and data-id if available
                if (el.id) {
                    elementXPaths['#' + el.id] = getXPathForElement(el);
                }
                
                // Store special attributes for interactive elements
                if (el.hasAttribute('__elementId')) {
                    elementXPaths[el.getAttribute('__elementId')] = getXPathForElement(el);
                }
                
                // Also capture numeric attributes that might be PlaywrightController's IDs
                const attributes = el.attributes;
                for (let j = 0; j < attributes.length; j++) {
                    const attr = attributes[j];
                    if (attr.name === '__elementId' || !isNaN(attr.value)) {
                        elementXPaths[attr.value] = getXPathForElement(el);
                    }
                }
            }
            
            return elementXPaths;
        }
        """
        try:
            res = await page.evaluate(js)
            return {str(k): str(v) for k, v in res.items() if k in element_ids}
        except Exception:
            logger.exception("XPath extraction failed")
            return {}

    async def _would_navigate_external(self, page: Page, element_id: str) -> bool:
        try:
            js = """
            (args) => {
              const [id, origin] = args;
              const selector = `[__elementId="${id}"]`;
              const el = document.querySelector(selector);
              if (!el) return false;
              
              // If no href, it's not a link - so not external
              const href = el.getAttribute('href');
              if (!href) return false;
              
              // Relative paths are always internal
              if (href.startsWith('/') || href.startsWith('#') || href.startsWith('./') || href.startsWith('../')) {
                return false;
              }
              
              // For absolute URLs, check the domain
              try {
                const a = document.createElement('a');
                a.href = href;
                // Empty hostname means it's a relative URL
                if (!a.hostname) return false;
                
                const host = a.hostname.replace(/^www\\./, '');
                const originHost = origin.replace(/^www\\./, '');
                
                // Allow subdomain variations - strip to domain.tld
                const hostParts = host.split('.');
                const originParts = originHost.split('.');
                
                // Take last 2 parts (domain.tld) if long enough
                const mainDomain = hostParts.length >= 2 ? 
                      hostParts.slice(-2).join('.') : host;
                const originDomain = originParts.length >= 2 ? 
                      originParts.slice(-2).join('.') : originHost;
                
                return mainDomain !== originDomain && host !== originHost;
              } catch(e) {
                // If parsing fails, err on the side of caution
                return false;
              }
            }
            """
            return await page.evaluate(js, [element_id, self._origin])
        except Exception:
            return False