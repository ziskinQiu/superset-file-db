import React from "react";

import { NotificationDto } from "../types";

export interface NotificationsProps {
  items: NotificationDto[];
  onDismiss: (id: string) => void;
}

export const Notifications: React.FC<NotificationsProps> = ({ items, onDismiss }) => {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="notifications-banner">
      <strong>{items.length} 个文件将在 7 天内过期</strong>
      <ul>
        {items.map((item) => (
          <li key={item.file_id}>
            {item.filename}（到期日 {item.expiry_time.slice(0, 10)}，剩 {item.days_left} 天）
            <button type="button" onClick={() => onDismiss(item.file_id)}>
              忽略
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
};
