type ComponentSwitchProps = {
  label: string;
  checked: boolean;
  disabled?: boolean;
  pending?: boolean;
  onChange?: (checked: boolean) => void;
};

export function ComponentSwitch({
  label,
  checked,
  disabled = false,
  pending = false,
  onChange,
}: ComponentSwitchProps) {
  return (
    <div className="component-switch-control">
      <span>{pending ? "切换中" : checked ? "已开启" : "已关闭"}</span>
      <button
        type="button"
        role="switch"
        aria-label={label}
        aria-checked={checked}
        className="component-switch"
        disabled={disabled || pending}
        onClick={() => onChange?.(!checked)}
      >
        <span aria-hidden="true" />
      </button>
    </div>
  );
}
