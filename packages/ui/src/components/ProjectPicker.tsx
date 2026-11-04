export interface ProjectOption {
  id: string;
  name: string;
  status?: "active" | "archived" | string;
}

export interface ProjectPickerProps {
  projects: ProjectOption[];
  value: string | null;
  onChange: (id: string | null) => void;
  placeholder?: string;
}

/** Выбор проекта в верхней полосе: select без подписи, aria-label="Проект". */
export function ProjectPicker({ projects, value, onChange, placeholder = "Выберите проект" }: ProjectPickerProps) {
  const active = projects.filter((p) => p.status !== "archived");
  const archived = projects.filter((p) => p.status === "archived");
  const known = projects.some((p) => p.id === value);
  return (
    <select
      className="select"
      aria-label="Проект"
      value={known ? (value ?? "") : ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="" disabled={projects.length > 0}>
        {projects.length ? placeholder : "Нет доступных проектов"}
      </option>
      {active.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
      {archived.length > 0 && (
        <optgroup label="Архив">
          {archived.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}
