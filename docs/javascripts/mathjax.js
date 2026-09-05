window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"], ["$", "$"]],
    displayMath: [["\\[", "\\]"], ["$$", "$$"]],
    processEscapes: true,
    processEnvironments: true
  },
  options: {
    ignoreHtmlClass: "tex2jax_ignore",
    processHtmlClass: "arithmatex|md-typeset"
  }
};

// Рендеринг MathJax при зміні сторінок (Instant Loading в MkDocs Material)
document$.subscribe(() => { 
  if (typeof MathJax !== "undefined" && MathJax.startup) {
    MathJax.startup.output.clearCache();
    MathJax.typesetClear();
    MathJax.texReset();
    MathJax.typesetPromise();
  }
});

// Рендеринг формул при відкритті спойлерів <details>
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("details").forEach((el) => {
    el.addEventListener("toggle", () => {
      if (el.open && typeof MathJax !== "undefined") {
        MathJax.typesetPromise([el]);
      }
    });
  });
});
