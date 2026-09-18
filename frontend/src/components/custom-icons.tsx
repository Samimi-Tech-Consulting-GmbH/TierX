export interface CustomIconProps {
  className?: string;
}

export function CloudIcon({ className }: CustomIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g transform="translate(23.275 0.48) scale(-0.55 0.55)">
        <path
          d="M33.5,34.5c3.689,0,7-3.529,7-7.409c0-3.649-2.65-7-6.02-7.34c0.06-0.47,0.09-0.98,0.09-1.49c0-5.99-4.631-10.84-10.36-10.84c-4.56,0-8.42,3.07-9.819,7.34c-0.711-0.21-1.461-0.27-2.221-0.32c-5.62-0.38-8.34,1.54-8.34,8.792c0,0.469,0.029,0.92,0.109,1.35C1.97,25.072,0.5,26.922,0.5,29.121c0,2.561,2.54,5.379,5,5.379H33.5L33.5,34.5z"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.636"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </g>
    </svg>
  );
}
