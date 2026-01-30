# Prometheus - Personal iMessage Bot

## Overview

Prometheus is a personalized iMessage bot that learns from your messaging history and responds to new messages in your authentic voice and tone. It acts as your digital twin for messaging, maintaining your communication style while you're busy or unavailable.

## Problem Statement

- You receive messages that need timely responses but can't always reply immediately
- Generic auto-replies feel impersonal and don't represent you
- Existing chatbots sound robotic and don't capture individual communication styles

## Solution

An AI-powered iMessage bot that:
1. Analyzes your historical iMessage conversations to learn your unique tone, vocabulary, and communication patterns
2. Responds to incoming messages in a way that sounds authentically like you
3. Operates seamlessly within the iMessage ecosystem on macOS

## Core Features

### Phase 1: Message Training
- [ ] Extract message history from macOS iMessage database (`~/Library/Messages/chat.db`)
- [ ] Parse and preprocess conversations (handle attachments, reactions, threads)
- [ ] Build a personalized language model/prompt that captures your tone
- [ ] Store training data securely

### Phase 2: Response Generation
- [ ] Integrate with Claude API for intelligent response generation
- [ ] Use few-shot learning with your message examples to match your style
- [ ] Handle context from conversation history
- [ ] Support different tones for different contacts (formal vs casual)

### Phase 3: iMessage Integration
- [ ] Monitor for new incoming messages
- [ ] Send responses through iMessage (AppleScript/Messages.app automation)
- [ ] Implement approval workflow (optional: review before sending)
- [ ] Handle group chats vs individual conversations

### Phase 4: Controls & Safety
- [ ] Whitelist/blacklist contacts for auto-reply
- [ ] Set active hours for the bot
- [ ] Manual override and conversation takeover
- [ ] Logging and audit trail of bot responses

## Technical Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Prometheus Bot                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Message    │    │    Tone      │    │   Response   │  │
│  │  Extractor   │───▶│   Analyzer   │───▶│  Generator   │  │
│  │  (chat.db)   │    │  (Training)  │    │  (Claude)    │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                    │         │
│  ┌──────────────┐    ┌──────────────┐             │         │
│  │   Message    │◀───│   iMessage   │◀────────────┘         │
│  │   Monitor    │    │    Sender    │                       │
│  │  (Incoming)  │    │ (AppleScript)│                       │
│  └──────────────┘    └──────────────┘                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Tech Stack

- **Language**: Python 3.11+
- **AI**: Claude API (Anthropic)
- **Database**: SQLite (reading chat.db), local SQLite for bot state
- **iMessage Integration**: AppleScript via `osascript`
- **Platform**: macOS only (iMessage requirement)

## File Structure

```
Prometheus/
├── src/
│   ├── extractor/       # Message history extraction
│   ├── analyzer/        # Tone analysis and training
│   ├── generator/       # Response generation
│   ├── imessage/        # iMessage monitoring and sending
│   └── config/          # Configuration management
├── data/                # Training data (gitignored)
├── tests/
├── requirements.txt
├── config.yaml          # User configuration
└── main.py              # Entry point
```

## Configuration

```yaml
# config.yaml
anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-sonnet-4-20250514

bot:
  active_hours:
    start: "09:00"
    end: "22:00"
  response_delay_seconds: 30  # Feel more human
  require_approval: false

contacts:
  whitelist: []  # Empty = all contacts
  blacklist: ["Boss Name", "Mom"]  # Never auto-reply to these

tone:
  default: "casual"
  overrides:
    "Work Contact": "professional"
```

## Privacy & Security Considerations

- All message data stays local on your machine
- No message content is stored externally
- API calls to Claude only include minimal context needed for response
- Sensitive conversations can be excluded via blacklist

## Open Questions

1. Should the bot notify you when it responds on your behalf?
2. How to handle messages that require action (e.g., "Can you call me?")?
3. Should there be a "confidence threshold" below which it asks for your input?
4. How to handle media/attachment messages?
5. Group chat behavior - should it respond differently or stay silent?

## Success Metrics

- Response authenticity: Friends can't tell it's not you
- Response latency: < 2 minutes from message received
- User override rate: How often you need to correct/retract responses

---

*Let's iterate on this PRD together. What aspects would you like to refine or expand?*
