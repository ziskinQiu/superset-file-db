import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { Notifications } from "./Notifications";
import { NotificationDto } from "../types";

const ITEMS: NotificationDto[] = [
  {
    file_id: "f1",
    filename: "soon.csv",
    expiry_time: "2026-09-28T10:00:00",
    days_left: 3,
  },
  {
    file_id: "f2",
    filename: "later.csv",
    expiry_time: "2026-09-30T10:00:00",
    days_left: 5,
  },
];

describe("Notifications", () => {
  it("renders the expiry banner with items", () => {
    render(<Notifications items={ITEMS} onDismiss={() => undefined} />);

    expect(screen.getByText("2 个文件将在 7 天内过期")).toBeInTheDocument();
    expect(screen.getByText(/soon\.csv/)).toBeInTheDocument();
    expect(screen.getByText(/later\.csv/)).toBeInTheDocument();
  });

  it("dismisses items one by one", () => {
    const onDismiss = vi.fn();
    render(<Notifications items={ITEMS} onDismiss={onDismiss} />);

    fireEvent.click(screen.getAllByRole("button", { name: "忽略" })[0]);
    expect(onDismiss).toHaveBeenCalledWith("f1");
  });

  it("renders nothing when there are no notifications", () => {
    const { container } = render(<Notifications items={[]} onDismiss={() => undefined} />);
    expect(container.firstChild).toBeNull();
  });
});
