from typing import Tuple, List, Dict, Any, Optional
from playwright.async_api import Page
import asyncio


class AnimationUtilsPlaywright:
    """
    A utility class for handling cursor animations and visual effects in Playwright.
    """

    def __init__(self) -> None:
        self.last_cursor_position: Tuple[float, float] = (0.0, 0.0)
        self.highlighted_elements: List[str] = []

    async def add_cursor_box(self, page: Page, identifier: str) -> None:
        """
        Highlight the element with the given identifier and insert a custom cursor on the page.

        Args:
            page (Page): The Playwright page object.
            identifier (str): The element identifier.
        """
        try:
            # 1. Highlight the element (if it exists)
            await page.evaluate(
                """
                (identifier) => {
                    const elm = document.querySelector(`[__elementId='${identifier}']`);
                    if (elm) {
                        elm.style.transition = 'border 0.3s ease-in-out';
                        elm.style.border = '2px solid red';
                    }
                }
                """,
                identifier,
            )
            
            # Track highlighted elements
            if identifier not in self.highlighted_elements:
                self.highlighted_elements.append(identifier)

            # Give time for the border transition
            await asyncio.sleep(0.3)

            # 2. Create a custom cursor (only if it doesn't already exist)
            await page.evaluate(
                """
                () => {
                    let cursor = document.getElementById('red-cursor');
                    if (!cursor) {
                        cursor = document.createElement('div');
                        cursor.id = 'red-cursor';
                        cursor.style.width = '12px';
                        cursor.style.height = '12px';
                        cursor.style.position = 'absolute';
                        cursor.style.borderRadius = '50%';
                        cursor.style.zIndex = '999999';        // Large z-index to appear on top
                        cursor.style.pointerEvents = 'none';    // Don't block clicks
                        // A nicer cursor: red ring with a white highlight and a soft shadow
                        cursor.style.background = 'radial-gradient(circle at center, #fff 20%, #f00 100%)';
                        cursor.style.boxShadow = '0 0 6px 2px rgba(255,0,0,0.5)';
                        cursor.style.transition = 'left 0.1s linear, top 0.1s linear';
                        document.body.appendChild(cursor);
                    }
                }
                """
            )
        except Exception:
            pass

    async def gradual_cursor_animation(
        self,
        page: Page,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        steps: int = 20,
        step_delay: float = 0.05,
    ) -> None:
        """
        Animate the cursor movement gradually from start to end coordinates.

        Args:
            page (Page): The Playwright page object.
            start_x (float): The starting x-coordinate.
            start_y (float): The starting y-coordinate.
            end_x (float): The ending x-coordinate.
            end_y (float): The ending y-coordinate.
            steps (int, optional): Number of small steps for the movement. Default: 20
            step_delay (float, optional): Delay (in seconds) between steps. Default: 0.05
        """
        # Ensure the cursor is on the page
        try:
            for step in range(steps):
                # Linear interpolation
                x = start_x + (end_x - start_x) * (step / steps)
                y = start_y + (end_y - start_y) * (step / steps)

                # Move the cursor via JS
                await page.evaluate(
                    """
                    ([x, y]) => {
                        const cursor = document.getElementById('red-cursor');
                        if (cursor) {
                            cursor.style.left = x + 'px';
                            cursor.style.top = y + 'px';
                        }
                    }
                    """,
                    [x, y],
                )

                await asyncio.sleep(step_delay)

            # Final position
            await page.evaluate(
                """
                ([x, y]) => {
                    const cursor = document.getElementById('red-cursor');
                    if (cursor) {
                        cursor.style.left = x + 'px';
                        cursor.style.top = y + 'px';
                    }
                }
                """,
                [end_x, end_y],
            )
        except Exception:
            pass
            # Store last cursor position if needed
        self.last_cursor_position = (end_x, end_y)

    async def remove_cursor_box(self, page: Page, identifier: str) -> None:
        """
        Remove the highlight from the element and the custom cursor from the page.

        Args:
            page (Page): The Playwright page object.
            identifier (str): The element identifier.
        """
        try:
            await page.evaluate(
                """
                (identifier) => {
                    // Remove highlight
                    const elm = document.querySelector(`[__elementId='${identifier}']`);
                    if (elm) {
                        elm.style.border = '';
                    }
                    // Remove cursor
                    const cursor = document.getElementById('red-cursor');
                    if (cursor) {
                        cursor.remove();
                    }
                }
                """,
                identifier,
            )
            
            # Remove from highlighted elements list
            if identifier in self.highlighted_elements:
                self.highlighted_elements.remove(identifier)
                
        except Exception:
            pass

    async def cleanup_animations(self, page: Page) -> None:
        """
        Clean up any cursor animations or highlights that were added by animate_actions.
        This includes removing the red cursor element and any element highlights.

        Args:
            page (Page): The Playwright page object.
        """
        try:
            # Remove cursor and highlights using the same approach as in remove_cursor_box
            await page.evaluate(
                """
                () => {
                    // Remove cursor
                    const cursor = document.getElementById('red-cursor');
                    if (cursor) {
                        cursor.remove();
                    }
                    // Remove highlights from all elements
                    const elements = document.querySelectorAll('[__elementId]');
                    elements.forEach(el => {
                        if (el.style.border && el.style.transition) {
                            el.style.border = '';
                            el.style.transition = '';
                        }
                    });
                }
                """
            )
            # Reset the last cursor position
            self.last_cursor_position = (0.0, 0.0)
            # Clear highlighted elements list
            self.highlighted_elements = []
        except Exception:
            pass
            
    async def show_all_marked_elements(self, page: Page, highlight_color: str = "rgba(255, 0, 0, 0.2)") -> Dict[str, Any]:
        """
        Highlight all elements with __elementId attribute to make them visible on the screen.
        Also returns information about the marked elements.
        
        Args:
            page (Page): The Playwright page object
            highlight_color (str): CSS color for the highlight. Default: "rgba(255, 0, 0, 0.2)"
            
        Returns:
            Dict[str, Any]: Information about marked elements (id, text, position)
        """
        try:
            # Show all marked elements with a highlight and tooltip
            element_info = await page.evaluate(
                """
                (highlightColor) => {
                    // Create a style for tooltips if it doesn't exist
                    let tooltipStyle = document.getElementById('element-tooltip-style');
                    if (!tooltipStyle) {
                        tooltipStyle = document.createElement('style');
                        tooltipStyle.id = 'element-tooltip-style';
                        tooltipStyle.innerHTML = `
                            .element-tooltip {
                                position: absolute;
                                background: rgba(0, 0, 0, 0.8);
                                color: white;
                                padding: 5px;
                                border-radius: 3px;
                                font-size: 12px;
                                z-index: 999998;
                                pointer-events: none;
                                max-width: 250px;
                                white-space: nowrap;
                                overflow: hidden;
                                text-overflow: ellipsis;
                            }
                        `;
                        document.head.appendChild(tooltipStyle);
                    }
                    
                    // Remove existing tooltips
                    document.querySelectorAll('.element-tooltip').forEach(el => el.remove());
                    
                    // Find all elements with __elementId
                    const markedElements = document.querySelectorAll('[__elementId]');
                    const elementsInfo = [];
                    
                    markedElements.forEach(el => {
                        const id = el.getAttribute('__elementId');
                        const rect = el.getBoundingClientRect();
                        
                        // Skip elements not in viewport or too small
                        if (rect.width < 2 || rect.height < 2 || 
                            rect.right < 0 || rect.bottom < 0 || 
                            rect.left > window.innerWidth || rect.top > window.innerHeight) {
                            return;
                        }
                        
                        // Highlight the element
                        el.dataset.originalBackgroundColor = el.style.backgroundColor || '';
                        el.style.transition = 'background-color 0.3s ease-in-out';
                        el.style.backgroundColor = highlightColor;
                        
                        // Add outline
                        el.dataset.originalOutline = el.style.outline || '';
                        el.style.outline = '2px dashed red';
                        
                        // Create tooltip with element ID
                        const tooltip = document.createElement('div');
                        tooltip.className = 'element-tooltip';
                        tooltip.textContent = `ID: ${id}`;
                        
                        // Position tooltip above the element
                        tooltip.style.left = `${rect.left}px`;
                        tooltip.style.top = `${rect.top - 25}px`;
                        
                        // Add tooltip to body
                        document.body.appendChild(tooltip);
                        
                        // Collect element info
                        elementsInfo.push({
                            id,
                            tag: el.tagName.toLowerCase(),
                            text: el.innerText || el.textContent || '',
                            position: {
                                x: rect.left,
                                y: rect.top,
                                width: rect.width,
                                height: rect.height
                            }
                        });
                    });
                    
                    // Return information about marked elements
                    return {
                        count: elementsInfo.length,
                        elements: elementsInfo
                    };
                }
                """,
                highlight_color,
            )
            
            return element_info
        except Exception as e:
            print(f"Error showing marked elements: {e}")
            return {"count": 0, "elements": []}
    
    async def hide_all_marked_elements(self, page: Page) -> None:
        """
        Remove highlights from all marked elements and their tooltips.
        
        Args:
            page (Page): The Playwright page object
        """
        try:
            await page.evaluate(
                """
                () => {
                    // Remove tooltips
                    document.querySelectorAll('.element-tooltip').forEach(el => el.remove());
                    
                    // Restore original styles for all marked elements
                    document.querySelectorAll('[__elementId]').forEach(el => {
                        if (el.dataset.originalBackgroundColor !== undefined) {
                            el.style.backgroundColor = el.dataset.originalBackgroundColor;
                            delete el.dataset.originalBackgroundColor;
                        }
                        
                        if (el.dataset.originalOutline !== undefined) {
                            el.style.outline = el.dataset.originalOutline;
                            delete el.dataset.originalOutline;
                        }
                    });
                }
                """
            )
        except Exception as e:
            print(f"Error hiding marked elements: {e}")
            
    async def add_action_effect(self, page: Page, action_type: str, element_id: Optional[str] = None, coords: Optional[Tuple[float, float]] = None) -> None:
        """
        Add visual effect for different action types (click, hover, etc.)
        
        Args:
            page (Page): The Playwright page object
            action_type (str): Type of action ('click', 'hover', 'type', etc.)
            element_id (Optional[str]): Element ID if action is on an element
            coords (Optional[Tuple[float, float]]): Coordinates if action is at a position
        """
        try:
            if element_id:
                # Get element position
                element_box = await page.evaluate(
                    """
                    (id) => {
                        const el = document.querySelector(`[__elementId='${id}']`);
                        if (!el) return null;
                        const rect = el.getBoundingClientRect();
                        return {
                            x: rect.left + rect.width/2,
                            y: rect.top + rect.height/2,
                            width: rect.width,
                            height: rect.height
                        };
                    }
                    """,
                    element_id
                )
                
                if not element_box:
                    return
                    
                x, y = element_box["x"], element_box["y"]
            elif coords:
                x, y = coords
            else:
                return
                
            # Create animation based on action type
            if action_type == "click":
                await page.evaluate(
                    """
                    ([x, y]) => {
                        // Create ripple effect
                        const ripple = document.createElement('div');
                        ripple.style.position = 'absolute';
                        ripple.style.left = (x - 20) + 'px';
                        ripple.style.top = (y - 20) + 'px';
                        ripple.style.width = '40px';
                        ripple.style.height = '40px';
                        ripple.style.borderRadius = '50%';
                        ripple.style.backgroundColor = 'rgba(255, 0, 0, 0.3)';
                        ripple.style.pointerEvents = 'none';
                        ripple.style.zIndex = '999997';
                        ripple.style.animation = 'ripple-animation 0.6s ease-out';
                        
                        // Add animation if not exists
                        if (!document.getElementById('ripple-keyframes')) {
                            const style = document.createElement('style');
                            style.id = 'ripple-keyframes';
                            style.innerHTML = `
                                @keyframes ripple-animation {
                                    0% { transform: scale(0.1); opacity: 1; }
                                    100% { transform: scale(2); opacity: 0; }
                                }
                            `;
                            document.head.appendChild(style);
                        }
                        
                        document.body.appendChild(ripple);
                        
                        // Remove after animation completes
                        setTimeout(() => {
                            ripple.remove();
                        }, 600);
                    }
                    """,
                    [x, y]
                )
            elif action_type == "hover":
                await page.evaluate(
                    """
                    ([x, y]) => {
                        // Create hover glow effect
                        const glow = document.createElement('div');
                        glow.style.position = 'absolute';
                        glow.style.left = (x - 15) + 'px';
                        glow.style.top = (y - 15) + 'px';
                        glow.style.width = '30px';
                        glow.style.height = '30px';
                        glow.style.borderRadius = '50%';
                        glow.style.boxShadow = '0 0 10px 5px rgba(0, 255, 255, 0.5)';
                        glow.style.pointerEvents = 'none';
                        glow.style.zIndex = '999997';
                        glow.style.opacity = '0';
                        glow.style.animation = 'hover-animation 1s ease-in-out infinite alternate';
                        
                        // Add animation if not exists
                        if (!document.getElementById('hover-keyframes')) {
                            const style = document.createElement('style');
                            style.id = 'hover-keyframes';
                            style.innerHTML = `
                                @keyframes hover-animation {
                                    0% { opacity: 0.2; transform: scale(0.9); }
                                    100% { opacity: 0.6; transform: scale(1.1); }
                                }
                            `;
                            document.head.appendChild(style);
                        }
                        
                        document.body.appendChild(glow);
                        
                        // Store reference to remove later
                        window.__currentHoverEffect = glow;
                    }
                    """,
                    [x, y]
                )
            elif action_type == "type":
                await page.evaluate(
                    """
                    ([x, y]) => {
                        // Create typing indicator
                        const indicator = document.createElement('div');
                        indicator.style.position = 'absolute';
                        indicator.style.left = (x + 10) + 'px';
                        indicator.style.top = (y - 20) + 'px';
                        indicator.style.padding = '3px 8px';
                        indicator.style.borderRadius = '4px';
                        indicator.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
                        indicator.style.color = 'white';
                        indicator.style.fontSize = '12px';
                        indicator.style.pointerEvents = 'none';
                        indicator.style.zIndex = '999997';
                        indicator.innerHTML = '✏️ typing...';
                        
                        document.body.appendChild(indicator);
                        
                        // Store reference to remove later
                        window.__currentTypeEffect = indicator;
                    }
                    """,
                    [x, y]
                )
        except Exception as e:
            print(f"Error adding action effect: {e}")
            
    async def remove_action_effect(self, page: Page, action_type: str) -> None:
        """
        Remove action effect by type
        
        Args:
            page (Page): The Playwright page object
            action_type (str): Type of action ('click', 'hover', 'type', etc.)
        """
        try:
            if action_type == "hover":
                await page.evaluate(
                    """
                    () => {
                        if (window.__currentHoverEffect) {
                            window.__currentHoverEffect.remove();
                            window.__currentHoverEffect = null;
                        }
                    }
                    """
                )
            elif action_type == "type":
                await page.evaluate(
                    """
                    () => {
                        if (window.__currentTypeEffect) {
                            window.__currentTypeEffect.remove();
                            window.__currentTypeEffect = null;
                        }
                    }
                    """
                )
        except Exception as e:
            print(f"Error removing action effect: {e}")
