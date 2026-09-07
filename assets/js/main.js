(function () {
  'use strict';

  // Theme toggle ----------------------------------------------------------
  var root = document.documentElement;
  var toggle = document.querySelector('.theme-toggle');
  function currentTheme() {
    var explicit = root.getAttribute('data-theme');
    if (explicit) return explicit;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  if (toggle) {
    toggle.addEventListener('click', function () {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
    });
  }

  // Mobile navigation -----------------------------------------------------
  var navToggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');
  if (navToggle && nav) {
    navToggle.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    nav.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') {
        nav.classList.remove('is-open');
        navToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // Publication filters ---------------------------------------------------
  var filters = document.querySelector('.filters');
  if (filters) {
    filters.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-filter]');
      if (!btn) return;
      var type = btn.getAttribute('data-filter');
      filters.querySelectorAll('button').forEach(function (b) {
        b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
      });
      document.querySelectorAll('.pub').forEach(function (p) {
        var show = type === 'all' || p.getAttribute('data-type') === type;
        p.classList.toggle('is-hidden', !show);
      });
      // Hide year headings with no visible entries.
      document.querySelectorAll('.pub-year').forEach(function (h) {
        var list = h.nextElementSibling;
        var visible = list && list.querySelector('.pub:not(.is-hidden)');
        h.classList.toggle('is-hidden', !visible);
      });
    });
  }
})();
