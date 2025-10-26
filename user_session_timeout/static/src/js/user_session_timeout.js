/** @odoo-module **/

import { session } from "@web/session";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// Define constants
const SESSION_TIMEOUT_DEFAULT = 15 * 60 * 1000; // Default: 15 minutes
let SESSION_TIMEOUT = SESSION_TIMEOUT_DEFAULT;
let timeoutId;
const localStorage = window.localStorage;

// Debounce utility
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// Define functions
function logout() {
    window.location.href = "/web/session/logout";
}

function resetTimer() {
    clearTimeout(timeoutId);
    if (session.uid) {
        timeoutId = setTimeout(logout, SESSION_TIMEOUT);
    }
}

let lastScrollY = window.scrollY;
let lastTouchY = null;

function handleUserInteraction(event) {
    if (event.type === "scroll") {
        const currentScrollY = window.scrollY;
        if (Math.abs(currentScrollY - lastScrollY) < 10) return; // Ignore small scrolls
        lastScrollY = currentScrollY;
    } else if (event.type === "touchmove" && event.touches?.length) {
        const touchY = event.touches[0].clientY;
        if (lastTouchY && Math.abs(touchY - lastTouchY) < 10) return; // Ignore small movements
        lastTouchY = touchY;
    }
    resetTimer();
    if (session.uid) {
        localStorage.setItem("userActive", Date.now());
    }
}

const debouncedHandleUserInteraction = debounce(handleUserInteraction, 100);

// Event listeners
const userInteractionEvents = [
    "mousemove",
    "mousedown",
    "keydown",
    "scroll",
    "touchstart",
    "touchmove",
    "input",
    "change",
    "wheel",
    "contextmenu",
    "drag",
    "drop",
];

// Service definition
const inactivityTimeoutService = {
    dependencies: ["orm"],
    async start(env, { orm }) {
        // Fetch user_inactivity_timeout from system parameters
        if (session.uid) {
            try {
                const result = await orm.searchRead(
                    "ir.config_parameter",
                    [["key", "=", "user_inactivity_timeout"]],
                    ["value"],
                    { limit: 1 }
                );
                if (result.length > 0 && result[0].value) {
                    SESSION_TIMEOUT = parseInt(result[0].value, 10) * 1000;
                }
            } catch (error) {
                console.error("Failed to fetch session timeout:", error);
            }
        }

        // Add event listeners
        if (session.uid) {
            userInteractionEvents.forEach((event) => {
                document.addEventListener(event, debouncedHandleUserInteraction, {
                    passive: true,
                    capture: false,
                });
            });
        }

        function handleVisibilityChange() {
            // Do not pause timers when tab is hidden; keep server-side timeout authoritative
            if (!document.hidden) {
                handleUserInteraction({});
            }
        }

        document.addEventListener("visibilitychange", handleVisibilityChange);
        window.addEventListener("focus", handleUserInteraction);
        window.addEventListener("load", handleUserInteraction);

        // Listen for storage events to sync timers across tabs
        const handleStorageEvent = (event) => {
            if (event.key === "userActive") {
                resetTimer();
            }
        };
        window.addEventListener("storage", handleStorageEvent);

        // Initialize timer
        resetTimer();

        // Cleanup function
        const cleanup = () => {
            userInteractionEvents.forEach((event) => {
                document.removeEventListener(event, debouncedHandleUserInteraction, { passive: true });
            });
            document.removeEventListener("visibilitychange", handleVisibilityChange);
            window.removeEventListener("focus", handleUserInteraction);
            window.removeEventListener("load", handleUserInteraction);
            window.removeEventListener("storage", handleStorageEvent);
            clearTimeout(timeoutId);
        };

        return { resetTimer, cleanup };
    },
};

// Register service
registry.category("services").add("inactivity_timeout", inactivityTimeoutService);

export default { resetTimer };