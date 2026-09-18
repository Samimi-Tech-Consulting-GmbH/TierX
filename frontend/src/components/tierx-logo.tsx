export function TierXLogo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        fill="currentColor"
        d="M12 2L4.18923 5.8186C3.95533 5.93295 3.78795 6.14963 3.7364 6.40484C2.68177 11.6252 4.82058 16.9744 9.18369 20.0286L10.8531 21.1972C11.1974 21.4382 11.5987 21.5587 12 21.5587Z"
      />
      {/* Full shield outline */}
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.1469 21.1972L14.8163 20.0286C19.1794 16.9744 21.3182 11.6252 20.2636 6.40484C20.212 6.14963 20.0447 5.93295 19.8108 5.8186L12 2L4.18923 5.8186C3.95533 5.93295 3.78795 6.14963 3.7364 6.40484C2.68177 11.6252 4.82058 16.9744 9.18369 20.0286L10.8531 21.1972C11.5417 21.6792 12.4583 21.6792 13.1469 21.1972Z"
      />
    </svg>
  );
}
