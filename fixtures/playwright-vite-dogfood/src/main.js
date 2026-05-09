const app = document.getElementById("app");

app.innerHTML = `
  <h1 data-testid="heading">Course Builder demo</h1>
  <label for="topic">Lesson topic</label>
  <input id="topic" data-testid="topic" type="text" />
  <button id="compile" data-testid="compile">Compile lesson</button>
  <div id="output" data-testid="output" role="status" aria-live="polite">
    No lesson compiled yet.
  </div>
`;

const topicEl = document.getElementById("topic");
const compileEl = document.getElementById("compile");
const outputEl = document.getElementById("output");

compileEl.addEventListener("click", () => {
  const topic = (topicEl.value || "").trim();
  if (!topic) {
    return;
  }
  outputEl.classList.add("compiling");
  setTimeout(() => {
    outputEl.textContent = `Compiled lesson: ${topic}`;
    outputEl.classList.remove("compiling");
    outputEl.classList.add("compiled");
  }, 250);
});
