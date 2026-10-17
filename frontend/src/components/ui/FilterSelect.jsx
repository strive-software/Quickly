import Dropdown from './Dropdown';
export default function FilterSelect({ label, value, onChange, options, className = '' }) {
  return <label className={`block min-w-0 text-xs font-medium text-gray-600 dark:text-gray-300 ${className}`}>
    <span className="mb-1 block">{label}</span>
    <Dropdown
      value={value}
      onChange={event => onChange(event.target.value)}
      className="w-full rounded-lg border border-gray-300 bg-white py-2 pl-3 pr-9 text-sm font-medium text-gray-900 shadow-sm outline-none transition-colors hover:border-teal-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-200 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:ring-teal-900"
    >
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </Dropdown>
  </label>;
}
