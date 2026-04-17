# Facebook Group Auto-Follow — Design Spec

## Overview

Tool tự động theo dõi (follow) tác giả bài viết và người comment trong một Facebook group, nhằm mục đích xây dựng network.

## Architecture

**Hybrid approach**: Claude Code làm control plane, gọi script Node.js con (`facebook-auto-follow/index.js`) để drive browser thông qua `mcp__browsermcp__` tools.

```
Claude Code (Control Plane)
    └── spawns subprocess: node facebook-auto-follow/index.js
            └── calls mcp__browsermcp__ tools
                    └── drives Brave browser (already logged into Facebook)
```

## Components

### 1. `facebook-auto-follow/index.js` — Entry Point

Nhận command-line args:
- `start <groupUrl>` — bắt đầu từ đầu với group cụ thể
- `resume <groupUrl>` — tiếp tục từ state trước của group đó
- `status` — in ra state hiện tại

Ví dụ:
```bash
node index.js start https://www.facebook.com/groups/242605124320242
node index.js resume https://www.facebook.com/groups/242605124320242
node index.js status
```

Parse args → load config + state → call `mcp__browsermcp__*` tools trong loop → save state after each post.

### 2. `facebook-auto-follow/state.json` — Runtime State

```json
{
  "groupUrl": "https://www.facebook.com/groups/242605124320242",
  "lastPostUrl": "https://www.facebook.com/groups/.../posts/123",
  "totalFollowed": 47,
  "lastRun": "2026-04-17T10:30:00Z"
}
```

Updated after each successful post processing.

### 3. `facebook-auto-follow/config.js` — Configuration

Group URL được truyền qua command line, không hardcode. File config chỉ chứa behavior settings:

```javascript
module.exports = {
  scrollDelayMin: 1500,   // min ms between scrolls
  scrollDelayMax: 4000,   // max ms between scrolls (randomized)
  actionDelayMin: 400,     // min ms between follow actions
  actionDelayMax: 1200,    // max ms between follow actions (randomized)
  hoverDelayMin: 300,      // min ms hover before click
  hoverDelayMax: 600,      // max ms hover before click
  readDelayMin: 2000,      // min ms "reading" a post
  readDelayMax: 5000,      // max ms "reading" a post
  maxRetries: 2,           // click retry count
  debugMode: false
}
```

### Anti-Spam / Anti-Detection Behavior

Script mô phỏng hành vi người thật để tránh Facebook flag:

**Randomized delays:**
- Mỗi action có delay ngẫu nhiên trong khoảng [min, max], không fix cứng
- Scroll delay: 1500-4000ms ngẫu nhiên
- Action delay: 400-1200ms ngẫu nhiên

**Human-like scrolling:**
- Ưu tiên dùng **keyboard** (Page Down) hoặc **mouse wheel** thay vì click scrollbar
- Scroll từng đoạn ngắn, có pause 1-2s giữa các lần scroll (như người đọc nội dung)
- Thỉnh thoảng scroll ngược lên trên một chút (simulate reviewing)
- Random scroll speed — không scroll cùng tốc độ mỗi lần

**Mouse movement:**
- Hover trước khi click: di chuột vào element, dừng 300-600ms rồi mới click
- Di chuột theo đường cong (bezier), không di thẳng từ A đến B
- Vị trí click không chính xác tâm button, bias trái/trái ngẫu nhiên

**Không click liên tục:**
- Giữa mỗi lần click "Theo dõi" có delay ngẫu nhiên 400-1200ms
- Không bao giờ ở exact same position khi click

**Natural interaction patterns:**
- Thỉnh thoảng dừng lại "đọc" nội dung bài viết 2-5s
- Không follow quá nhanh — cảm giác như có người ngồi đọc thật sự

## Flow

```
1. node index.js start <groupUrl>
      → load config (groupUrl from args)
      → mcp__browsermcp__browser_navigate(groupUrl)
      → loop:
          a. snapshot → find post timestamp links
          b. click timestamp → open post dialog
          c. snapshot dialog → find author "Theo dõi" button
          d. click follow → wait → verify "Đang theo dõi"
          e. scroll dialog → find commenter "Theo dõi" buttons → click each
          f. close dialog → save state
          g. scroll feed → load more posts → repeat
      → Ctrl+C or no more posts → save state + exit
```

## Follow Button Detection

| State | Text | Action |
|-------|------|--------|
| Not following | "Theo dõi" | Click |
| Following | "Đang theo dõi" [disabled] | Skip |
| Following (alt) | "Đang theo dõi" (not disabled) | Skip |

Button identified by exact text match. Disabled attribute check for primary "following" state.

## Post Dialog Opening

1. Snapshot DOM in main feed
2. Find timestamp element (link or span with time-like text, near author name)
3. Click timestamp → dialog opens
4. Wait for dialog by snapshotting until dialog content detected

## Comment Scrolling

1. In open dialog, scroll down using keyboard or scroll element
2. After each scroll, snapshot
3. Find new "Theo dõi" buttons (not yet followed)
4. Click each, wait for confirmation
5. Continue scrolling until no new follow buttons appear

## Error Handling

- **Click fail**: retry 2x, skip if still fails
- **Page timeout**: refresh page, continue from last state
- **Dialog won't open**: skip this post, move to next
- **Script crash**: state already saved, can resume

## Stop Conditions

- No more posts in feed after scrolling to bottom
- User presses Ctrl+C
- Unrecoverable error

## Out of Scope

- Auto-comment, auto-react
- Comment reply interactions (level 1 comments only)
- Login — assumes browser already logged in
- Scheduling — manual trigger only

## Quality Objectives

- Zero false positives (never click "Đang theo dõi")
- No missed visible "Theo dõi" buttons
- Resume-safe after sudden stop
- Mimics human behavior to avoid Facebook spam detection
