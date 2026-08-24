/**
 * Canonical department list shown in the department combobox.
 *
 * `department` is still stored as a free-text string on the backend
 * (see backend/app/models/user.py — StudentRegisterRequest.department: str),
 * so picking a value here doesn't require any backend change. The list
 * exists purely so students get consistent, typeable+selectable options
 * instead of a blank free-text box, while still allowing a value that
 * isn't in this list (e.g. a department this college has that isn't
 * common elsewhere) to be typed in directly.
 */
export const DEPARTMENTS = [
  "Computer Science and Engineering",
  "Information Technology",
  "Electronics and Communication Engineering",
  "Electrical Engineering",
  "Mechanical Engineering",
  "Civil Engineering",
  "Chemical Engineering",
  "Artificial Intelligence and Data Science",
  "Biotechnology",
  "Aerospace Engineering",
] as const;