// Page behavior for the web UI. Loaded as /static/app.js. Inline scripts are blocked by the CSP.
//
// 1. Job form: the auth type and pagination type selects show only the fields that apply to
//    the chosen type. Fields carry data-show-for="<type> <type> ...". Without JavaScript all
//    fields stay visible and the form still works.
// 2. Forms with data-confirm ask the user before they submit (delete and reset).
(function () {
  "use strict";

  var CHOICE_SELECTOR = "select[name='auth_type'], select[name='pagination_type']";

  function refreshFields(form) {
    var chosen = [];
    form.querySelectorAll(CHOICE_SELECTOR).forEach(function (select) {
      chosen.push(select.value);
    });
    form.querySelectorAll("[data-show-for]").forEach(function (element) {
      var allowed = element.getAttribute("data-show-for").split(/\s+/);
      var applies = chosen.some(function (value) {
        return allowed.indexOf(value) !== -1;
      });
      element.hidden = !applies;
    });
  }

  function confirmBeforeSubmit(form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    });
  }

  function init() {
    document.querySelectorAll("form").forEach(function (form) {
      if (form.querySelector(CHOICE_SELECTOR)) {
        refreshFields(form);
        form.querySelectorAll(CHOICE_SELECTOR).forEach(function (select) {
          select.addEventListener("change", function () {
            refreshFields(form);
          });
        });
      }
      if (form.hasAttribute("data-confirm")) {
        confirmBeforeSubmit(form);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
