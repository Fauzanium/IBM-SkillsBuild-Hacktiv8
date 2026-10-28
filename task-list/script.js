/**
 * script.js — Task List App
 * ─────────────────────────────────────────────────────────────
 * Architecture: simple MVC-lite pattern
 *   • state   – single source of truth (tasks array + active filter)
 *   • render  – pure function: re-draws the UI from state
 *   • events  – user interactions that mutate state, then call render
 * ─────────────────────────────────────────────────────────────
 */

"use strict";

/* ═══════════════════════════════════════════════════
   1. STATE
   ═══════════════════════════════════════════════════ */

/**
 * @typedef {{ id: string, text: string, completed: boolean }} Task
 */

/** @type {{ tasks: Task[], filter: 'all'|'active'|'completed', editingId: string|null }} */
const state = {
  tasks: loadFromStorage(),   // persisted in localStorage
  filter: "all",
  editingId: null,            // ID of the task currently being edited
};

/* ═══════════════════════════════════════════════════
   2. DOM REFERENCES
   ═══════════════════════════════════════════════════ */

const taskForm          = document.getElementById("task-form");
const taskInput         = document.getElementById("task-input");
const formBtn           = document.getElementById("form-btn");
const btnLabel          = document.getElementById("btn-label");
const btnIcon           = document.getElementById("btn-icon");
const cancelEditWrapper = document.getElementById("cancel-edit-wrapper");
const cancelEditBtn     = document.getElementById("cancel-edit-btn");
const taskList          = document.getElementById("task-list");
const emptyState        = document.getElementById("empty-state");
const taskCounter       = document.getElementById("task-counter");
const clearCompletedBtn = document.getElementById("clear-completed-btn");
const filterTabs        = document.querySelectorAll(".filter-tab");
const toast             = document.getElementById("toast");

/* ═══════════════════════════════════════════════════
   3. RENDER
   ═══════════════════════════════════════════════════ */

/**
 * Re-renders the entire task list based on current state.
 * Called after every state mutation.
 */
function render() {
  const filtered = getFilteredTasks();

  // Clear existing list items
  taskList.innerHTML = "";

  if (filtered.length === 0) {
    emptyState.classList.remove("hidden");
  } else {
    emptyState.classList.add("hidden");
    filtered.forEach((task) => {
      taskList.appendChild(createTaskElement(task));
    });
  }

  updateCounter();
  updateFilterTabs();
  persistToStorage();
}

/**
 * Creates a single task list item element.
 * @param {Task} task
 * @returns {HTMLLIElement}
 */
function createTaskElement(task) {
  const li = document.createElement("li");
  li.className =
    "task-item flex items-center gap-3 bg-gray-50 rounded-xl px-4 py-3 " +
    "border border-transparent hover:border-blue-100 hover:bg-blue-50/30 transition duration-200 group";
  li.dataset.id = task.id;

  // ── Checkbox ──
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "task-checkbox";
  checkbox.checked = task.completed;
  checkbox.setAttribute("aria-label", `Mark "${task.text}" as ${task.completed ? "active" : "completed"}`);
  checkbox.addEventListener("change", () => toggleComplete(task.id));

  // ── Task text ──
  const span = document.createElement("span");
  span.className = "task-text flex-1 text-sm text-gray-700 break-words min-w-0" +
    (task.completed ? " completed" : "");
  span.textContent = task.text;

  // ── Highlight if currently editing ──
  if (state.editingId === task.id) {
    li.classList.add("border-brand-blueLight", "bg-blue-50/50");
  }

  // ── Edit button ──
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "action-btn edit-btn opacity-0 group-hover:opacity-100 focus:opacity-100";
  editBtn.setAttribute("aria-label", `Edit task: ${task.text}`);
  editBtn.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2"
         viewBox="0 0 24 24" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round"
            d="M15.232 5.232l3.536 3.536M9 13l-4 1 1-4 9.293-9.293a1 1 0 011.414 0l2.586 2.586a1 1 0 010 1.414L9 13z"/>
    </svg>`;
  editBtn.addEventListener("click", () => startEdit(task.id));

  // ── Delete button ──
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "action-btn delete-btn opacity-0 group-hover:opacity-100 focus:opacity-100";
  deleteBtn.setAttribute("aria-label", `Delete task: ${task.text}`);
  deleteBtn.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2"
         viewBox="0 0 24 24" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round"
            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M8 7V5a2 2 0 012-2h4a2 2 0 012 2v2"/>
    </svg>`;
  deleteBtn.addEventListener("click", () => deleteTask(task.id));

  li.append(checkbox, span, editBtn, deleteBtn);
  return li;
}

/**
 * Updates the "X tasks left" counter (counts only active tasks).
 */
function updateCounter() {
  const activeCount = state.tasks.filter((t) => !t.completed).length;
  taskCounter.textContent = `${activeCount} task${activeCount !== 1 ? "s" : ""} left`;
}

/**
 * Applies the active-tab styling to the currently selected filter.
 */
function updateFilterTabs() {
  filterTabs.forEach((tab) => {
    const isActive = tab.dataset.filter === state.filter;
    tab.classList.toggle("active-tab", isActive);
  });
}

/* ═══════════════════════════════════════════════════
   4. CRUD OPERATIONS
   ═══════════════════════════════════════════════════ */

/**
 * Handles form submission for both adding and updating a task.
 * @param {SubmitEvent} e
 */
function handleFormSubmit(e) {
  e.preventDefault();

  const text = taskInput.value.trim();
  if (!text) {
    shakInput();
    return;
  }

  if (state.editingId) {
    // ── UPDATE mode ──
    updateTask(state.editingId, text);
  } else {
    // ── CREATE mode ──
    addTask(text);
  }
}

/**
 * Creates a new task and prepends it to the list.
 * @param {string} text
 */
function addTask(text) {
  const newTask = {
    id: generateId(),
    text,
    completed: false,
  };

  state.tasks.unshift(newTask); // newest task at the top
  resetForm();
  render();
  showToast("Task added!");
}

/**
 * Enters edit mode for a given task.
 * Populates the input field with the task's current text.
 * @param {string} id
 */
function startEdit(id) {
  const task = findTaskById(id);
  if (!task) return;

  state.editingId = id;
  taskInput.value = task.text;
  taskInput.focus();

  // Swap form button to "Update" mode
  btnLabel.textContent = "Update";
  btnIcon.innerHTML = `
    <path stroke-linecap="round" stroke-linejoin="round"
          d="M5 13l4 4L19 7"/>`;
  cancelEditWrapper.classList.remove("hidden");

  render(); // re-render to highlight the edited item
}

/**
 * Updates the text of an existing task.
 * @param {string} id
 * @param {string} newText
 */
function updateTask(id, newText) {
  const task = findTaskById(id);
  if (!task) return;

  task.text = newText;
  resetForm();
  render();
  showToast("Task updated!");
}

/**
 * Toggles the completed status of a task.
 * @param {string} id
 */
function toggleComplete(id) {
  const task = findTaskById(id);
  if (!task) return;

  task.completed = !task.completed;
  render();
}

/**
 * Removes a task by ID with a brief exit animation.
 * @param {string} id
 */
function deleteTask(id) {
  const li = taskList.querySelector(`[data-id="${id}"]`);

  const removeFromState = () => {
    state.tasks = state.tasks.filter((t) => t.id !== id);
    // If we were editing this task, cancel edit mode too
    if (state.editingId === id) resetForm();
    render();
    showToast("Task deleted.");
  };

  if (li) {
    // Play exit animation, then mutate state
    li.classList.add("removing");
    li.addEventListener("animationend", removeFromState, { once: true });
  } else {
    removeFromState();
  }
}

/**
 * Removes all completed tasks at once.
 */
function clearCompleted() {
  const completedCount = state.tasks.filter((t) => t.completed).length;
  if (completedCount === 0) return;

  state.tasks = state.tasks.filter((t) => !t.completed);
  render();
  showToast(`${completedCount} completed task${completedCount !== 1 ? "s" : ""} cleared.`);
}

/* ═══════════════════════════════════════════════════
   5. FILTER
   ═══════════════════════════════════════════════════ */

/**
 * Returns the subset of tasks matching the current filter.
 * @returns {Task[]}
 */
function getFilteredTasks() {
  switch (state.filter) {
    case "active":    return state.tasks.filter((t) => !t.completed);
    case "completed": return state.tasks.filter((t) => t.completed);
    default:          return state.tasks; // "all"
  }
}

/**
 * Sets the active filter and re-renders.
 * @param {'all'|'active'|'completed'} filter
 */
function setFilter(filter) {
  state.filter = filter;
  render();
}

/* ═══════════════════════════════════════════════════
   6. HELPERS
   ═══════════════════════════════════════════════════ */

/**
 * Generates a short unique ID using timestamp + random suffix.
 * @returns {string}
 */
function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

/**
 * Finds a task by its ID.
 * @param {string} id
 * @returns {Task|undefined}
 */
function findTaskById(id) {
  return state.tasks.find((t) => t.id === id);
}

/**
 * Resets the form to its default "Add" state and clears editing mode.
 */
function resetForm() {
  taskInput.value = "";
  state.editingId = null;
  btnLabel.textContent = "Add";
  btnIcon.innerHTML = `
    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>`;
  cancelEditWrapper.classList.add("hidden");
}

/**
 * Briefly shakes the input field to signal invalid (empty) submission.
 */
function shakInput() {
  taskInput.classList.add("shake");
  taskInput.addEventListener("animationend", () => taskInput.classList.remove("shake"), { once: true });
}

/** Toast timeout handle — kept so we can clear it if a new toast fires quickly. */
let toastTimeout = null;

/**
 * Shows a brief toast notification at the bottom of the screen.
 * @param {string} message
 */
function showToast(message) {
  clearTimeout(toastTimeout);
  toast.textContent = message;
  toast.classList.add("show");
  toastTimeout = setTimeout(() => toast.classList.remove("show"), 2200);
}

/* ═══════════════════════════════════════════════════
   7. PERSISTENCE (localStorage)
   ═══════════════════════════════════════════════════ */

const STORAGE_KEY = "tasklist_tasks";

/**
 * Loads tasks from localStorage. Returns an empty array if none found.
 * @returns {Task[]}
 */
function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

/**
 * Saves the current tasks array to localStorage.
 */
function persistToStorage() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.tasks));
  } catch {
    // Silently ignore storage quota errors
  }
}

/* ═══════════════════════════════════════════════════
   8. EVENT LISTENERS
   ═══════════════════════════════════════════════════ */

// Form submit (add or update)
taskForm.addEventListener("submit", handleFormSubmit);

// Cancel edit mode
cancelEditBtn.addEventListener("click", () => {
  resetForm();
  render();
});

// Filter tabs
filterTabs.forEach((tab) => {
  tab.addEventListener("click", () => setFilter(tab.dataset.filter));
});

// Clear completed
clearCompletedBtn.addEventListener("click", clearCompleted);

// Allow pressing Escape to cancel edit
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.editingId) {
    resetForm();
    render();
  }
});

/* ═══════════════════════════════════════════════════
   9. INIT
   ═══════════════════════════════════════════════════ */

// Initial render on page load
render();
