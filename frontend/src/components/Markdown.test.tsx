import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

describe("Markdown (TC-AGT-09)", () => {
  it("renders formatting and tables", () => {
    const { container } = render(<Markdown text={"**Sideways**\n\n| Regime | Days |\n|---|---|\n| Bull | 128 |"} />);
    expect(container.querySelector("strong")).toHaveTextContent("Sideways");
    expect(container.querySelector("table td")).toHaveTextContent("Bull");
  });

  it("drops raw HTML and never renders images", () => {
    const { container } = render(
      <Markdown text={'Hi <img src=x onerror="alert(1)"> <script>alert(1)</script> ![p](http://evil.test/p.png) <b>b</b>'} />,
    );
    expect(container.querySelector("img, script, b")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
  });

  it("makes links safe", () => {
    const { container } = render(<Markdown text={"[ok](https://nseindia.com) [bad](javascript:alert(1))"} />);
    const [ok, bad] = Array.from(container.querySelectorAll("a"));
    expect(ok).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(ok).toHaveAttribute("target", "_blank");
    expect(bad?.getAttribute("href") ?? "").not.toContain("javascript");
  });
});
