import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow">
      {children}
    </a>
  ),
};

/** AI text, safely (TC-AGT-09): Markdown only - raw HTML is dropped, images are never loaded
 *  (no tracking pixels, no fake screenshots), links open in a new tab without a referrer.
 *  react-markdown never uses innerHTML and strips javascript: URLs by default. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-ai">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        disallowedElements={["img"]}
        unwrapDisallowed={false}
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
