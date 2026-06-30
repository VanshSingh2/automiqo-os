/*
  Tiny local icon set (feather/lucide-style SVGs).
  Self-contained so the UI builds regardless of the installed icon library.
*/
import * as React from "react";

type P = { className?: string; strokeWidth?: number };

function Svg({ className, strokeWidth = 2, children }: P & { children: React.ReactNode }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      width="1em"
      height="1em"
    >
      {children}
    </svg>
  );
}

export const LayoutDashboard = (p: P) => (
  <Svg {...p}><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></Svg>
);
export const MessagesSquare = (p: P) => (
  <Svg {...p}><path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" /><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" /></Svg>
);
export const Activity = (p: P) => (
  <Svg {...p}><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></Svg>
);
export const Bot = (p: P) => (
  <Svg {...p}><rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /><line x1="8" y1="16" x2="8" y2="16" /><line x1="16" y1="16" x2="16" y2="16" /></Svg>
);
export const CheckSquare = (p: P) => (
  <Svg {...p}><polyline points="9 11 12 14 22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></Svg>
);
export const FileText = (p: P) => (
  <Svg {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></Svg>
);
export const SlidersHorizontal = (p: P) => (
  <Svg {...p}><line x1="21" y1="6" x2="10" y2="6" /><line x1="6" y1="6" x2="3" y2="6" /><line x1="21" y1="12" x2="14" y2="12" /><line x1="10" y1="12" x2="3" y2="12" /><line x1="21" y1="18" x2="16" y2="18" /><line x1="12" y1="18" x2="3" y2="18" /><circle cx="8" cy="6" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="14" cy="18" r="2" /></Svg>
);
export const DollarSign = (p: P) => (
  <Svg {...p}><line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></Svg>
);
export const CalendarCheck = (p: P) => (
  <Svg {...p}><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /><polyline points="9 16 11 18 15 14" /></Svg>
);
export const CheckCircle2 = (p: P) => (
  <Svg {...p}><circle cx="12" cy="12" r="10" /><polyline points="8 12 11 15 16 9" /></Svg>
);
export const UserX = (p: P) => (
  <Svg {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><line x1="17" y1="8" x2="22" y2="13" /><line x1="22" y1="8" x2="17" y2="13" /></Svg>
);
export const Users = (p: P) => (
  <Svg {...p}><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></Svg>
);
export const ArrowRight = (p: P) => (
  <Svg {...p}><line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" /></Svg>
);
export const Send = (p: P) => (
  <Svg {...p}><line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" /></Svg>
);
export const Check = (p: P) => (
  <Svg {...p}><polyline points="20 6 9 17 4 12" /></Svg>
);
export const X = (p: P) => (
  <Svg {...p}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></Svg>
);
