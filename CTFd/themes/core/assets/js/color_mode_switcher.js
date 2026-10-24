"use strict";

/**
 * Get user preferred theme from their past choice. Dark mode is the default
 * theme, so the browser color-scheme is intentionally not consulted.
 * @returns {String} User preferred theme
 */
function getPreferredTheme() {
  const storedTheme = localStorage.getItem("theme");
  if (storedTheme === "light" || storedTheme === "dark") {
    return storedTheme;
  }
  return "dark";
}

/**
 * Update navbar icon to match given theme.
 * @param {String} theme - 'dark' or 'light'
 */
function showActiveTheme(theme) {
  document.querySelectorAll(".theme-switch i.fas").forEach(icon => {
    icon.classList.toggle("fa-moon", theme === "dark");
    icon.classList.toggle("fa-sun", theme !== "dark");
  });
}

// Change body theme early to prevent flash
let currentTheme = getPreferredTheme();
document.documentElement.setAttribute("data-bs-theme", currentTheme);

window.addEventListener("load", () => {
  showActiveTheme(currentTheme);

  // On button click, switch
  document.querySelectorAll(".theme-switch").forEach(e => {
    e.addEventListener("click", ev => {
      currentTheme = currentTheme === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-bs-theme", currentTheme);
      localStorage.setItem("theme", currentTheme);
      showActiveTheme(currentTheme);
      ev.preventDefault();
    });
  });
});
