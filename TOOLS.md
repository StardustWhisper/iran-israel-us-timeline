# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

## DALI

- 图片生成默认由 **dali** 负责。
- 生成完成后，**默认直接发送给 Lambda**，除非他明确说只生成不发送。
- 每次 **dali** 出图时，除了发送图片本身，**必须同时说明所用模型名**，方便后续复现、对比和调优。

Add whatever helps you do your job. This is your cheat sheet.
