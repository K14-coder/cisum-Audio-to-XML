import type { RightsNotice as Notice } from "../api/types";

type Props = {
  notice: Notice;
  checked?: boolean;
  onChange?: (checked: boolean) => void;
};

/** The rights notice box. With `onChange` it also renders the required checkbox. */
export function RightsNotice({ notice, checked = false, onChange }: Props) {
  return (
    <section className="rights-notice" aria-labelledby="rights-notice-title">
      <h3 id="rights-notice-title">{notice.title}</h3>
      {notice.paragraphs.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
      {onChange && (
        <label className="checkbox rights-checkbox">
          <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} required />
          <span>{notice.checkbox_label}</span>
        </label>
      )}
    </section>
  );
}
