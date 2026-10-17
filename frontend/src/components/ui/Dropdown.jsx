import { forwardRef } from 'react';

// Native selection behavior with the app-wide dropdown appearance from index.css.
// Keeping the select element preserves form events, keyboard use and mobile pickers.
const Dropdown = forwardRef(function Dropdown({ className = '', compact = false, children, ...props }, ref) {
  return <select ref={ref} className={`app-dropdown${compact ? ' app-dropdown--compact' : ''} ${className}`} {...props}>{children}</select>;
});

export default Dropdown;
