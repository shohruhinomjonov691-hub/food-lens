const base = { fill: "none", stroke: "currentColor", strokeWidth: 2.2, strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const, "aria-hidden": true };

export const Logo = () => (
  <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="14" fill="#b93d0b" /><circle cx="16" cy="16" r="7.5" fill="#fff8f0" />
    <circle cx="16" cy="16" r="3" fill="#b93d0b" />
  </svg>
);
export const ImageIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" {...base} strokeWidth={2}>
    <path d="M4 16l4.5-4.5a2 2 0 0 1 2.8 0L16 16" /><path d="M14 14l1.5-1.5a2 2 0 0 1 2.8 0L20 14" />
    <rect x="3" y="4" width="18" height="16" rx="3" /><circle cx="15.5" cy="8.5" r="1.5" />
  </svg>
);
export const Shield = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...base}>
    <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" /><path d="M9 12l2 2 4-4" />
  </svg>
);
export const Search = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" {...base} strokeWidth={2}>
    <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" />
  </svg>
);
export const CropIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" {...base} strokeWidth={2}>
    <path d="M6 2v14a2 2 0 0 0 2 2h14" /><path d="M18 22V8a2 2 0 0 0-2-2H2" />
  </svg>
);
export const Question = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" {...base}>
    <circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6" />
    <circle cx="12" cy="17" r=".6" fill="currentColor" />
  </svg>
);
export const Info = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...base}>
    <circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><circle cx="12" cy="7.6" r=".6" fill="currentColor" />
  </svg>
);
export const Alert = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" {...base}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5" /><circle cx="12" cy="16.5" r=".6" fill="currentColor" />
  </svg>
);
export const FileX = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" {...base}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M10 12l4 4M14 12l-4 4" />
  </svg>
);
