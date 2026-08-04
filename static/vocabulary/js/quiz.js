(function () {
  const form = document.querySelector("[data-quiz-form]");
  if (!form) {
    return;
  }

  const blocks = Array.from(document.querySelectorAll("[data-question-block]"));
  const counter = document.querySelector("[data-answered-count]");

  function updateState() {
    let answered = 0;
    blocks.forEach((block) => {
      const labels = Array.from(block.querySelectorAll(".choice"));
      const checked = block.querySelector("input[type='radio']:checked");
      labels.forEach((label) => label.classList.remove("is-selected"));
      if (checked) {
        answered += 1;
        checked.closest(".choice").classList.add("is-selected");
      }
    });
    if (counter) {
      counter.textContent = `已作答 ${answered} / ${blocks.length}`;
    }
  }

  form.addEventListener("change", updateState);
  form.addEventListener("submit", (event) => {
    const unanswered = blocks.length - blocks.filter((block) => {
      return block.querySelector("input[type='radio']:checked");
    }).length;
    if (unanswered > 0) {
      const confirmed = window.confirm(`還有 ${unanswered} 題尚未作答，仍要送出嗎？`);
      if (!confirmed) {
        event.preventDefault();
      }
    }
  });

  updateState();
})();
