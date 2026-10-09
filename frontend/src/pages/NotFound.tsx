import { Link } from "react-router";

export function NotFound() {
  return (
    <div className="mx-auto max-w-md pt-20 text-center">
      <h1 className="text-2xl font-bold text-ink">Page not found</h1>
      <p className="mt-2 text-ink-2">That page doesn't exist.</p>
      <Link to="/" className="mt-4 inline-block font-semibold text-sky-300 underline underline-offset-2">
        Go to today's regime
      </Link>
    </div>
  );
}
