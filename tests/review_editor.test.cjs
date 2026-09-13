// Offline interaction tests: node --test tests/review_editor.test.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(value, start, end, direction = "forward") {
  let handler;
  const editor = {
    value, selectionStart: start, selectionEnd: end, selectionDirection: direction,
    scrollTop: 80, scrollLeft: 0, inputEvents: 0,
    matches: () => true,
    setRangeText(text, from, to) {
      this.value = this.value.slice(0, from) + text + this.value.slice(to);
    },
    setSelectionRange(from, to, direction) {
      this.selectionStart = from; this.selectionEnd = to; this.selectionDirection = direction;
    },
    dispatchEvent(event) { assert.equal(event.type, "input"); this.inputEvents++; },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/static/review-editor.js"), "utf8"), {
    document: { addEventListener(name, fn) { assert.equal(name, "keydown"); handler = fn; } }, Event,
  });
  function press(overrides = {}) {
    const event = { target: editor, key: "*", prevented: false,
      preventDefault() { this.prevented = true; }, ...overrides };
    handler(event);
    return event;
  }
  return { editor, press };
}

test("wrap selection, preserving surrounding text; second asterisk makes bold", () => {
  const { editor, press } = setup("try the noodles today", 8, 15, "backward");
  assert.equal(press({ shiftKey: true }).prevented, true);
  assert.equal(editor.value, "try the *noodles* today");
  assert.deepEqual([editor.selectionStart, editor.selectionEnd, editor.selectionDirection], [9, 16, "backward"]);
  press();
  assert.equal(editor.value, "try the **noodles** today");
  assert.equal(editor.value.slice(editor.selectionStart, editor.selectionEnd), "noodles");
  assert.equal(editor.scrollTop, 80);
  assert.equal(editor.inputEvents, 2);
});

test("wrap multiline text", () => {
  const { editor, press } = setup("one\ntwo", 0, 7);
  press();
  assert.equal(editor.value, "*one\ntwo*");
});

test("leave ordinary typing, shortcuts and composition alone", () => {
  for (const overrides of [{ key: "a" }, { ctrlKey: true }, { metaKey: true }, { altKey: true }, { isComposing: true }]) {
    const { editor, press } = setup("dish", 0, 4);
    assert.equal(press(overrides).prevented, false);
    assert.equal(editor.value, "dish");
  }
  const { editor, press } = setup("dish", 2, 2);
  assert.equal(press().prevented, false);
  assert.equal(editor.value, "dish");
});

test("ignore other fields and read-only editors", () => {
  for (const overrides of [{ matches: () => false }, { readOnly: true }, { disabled: true }]) {
    const { editor, press } = setup("dish", 0, 4);
    Object.assign(editor, overrides);
    assert.equal(press().prevented, false);
  }
});
