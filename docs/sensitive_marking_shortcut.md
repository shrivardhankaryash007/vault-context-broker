# Sensitive Marking Shortcut Setup Runbook

This guide explains how to wire the `vault-context mark-sensitive` command to a keyboard shortcut or toolbar button in Obsidian or macOS. This enables you to consciously mark the active note as sensitive/restricted with a single action.

---

## Method 1: Obsidian Shell Commands Plugin (Cross-Platform / Recommended)

This method uses the popular **Shell Commands** Obsidian plugin to run the CLI tool directly on the active file.

### Prerequisites
1. In Obsidian, go to **Settings** > **Community plugins** > **Browse**.
2. Search for and install **Shell Commands** by Stefan Elfsson. Enable the plugin.

### Setup
1. Go to **Settings** > **Shell Commands** > **New Command**.
2. Set the following fields:
   - **Command:** 
     ```bash
     /path/to/vault-context-mcp/.venv/bin/vault-context mark-sensitive "{{file_path:absolute}}"
     ```
     *(Make sure the path to your `.venv/bin/vault-context` binary matches your development directory).*
   - **Description / Title:** `Mark Active Note Sensitive`
3. Click **Save**.
4. To bind a hotkey:
   - Go to Obsidian **Settings** > **Hotkeys**.
   - Search for `Shell Commands: Mark Active Note Sensitive`.
   - Click the plus (`+`) icon and assign your preferred hotkey (e.g., `Cmd + Option + S` or similar).

Now, pressing the hotkey while editing any note will automatically invoke the tool, adding `sensitivity: restricted` and the `sensitive` tag to the note's frontmatter.

---

## Method 2: macOS Shortcuts App (OS-Level)

You can create a macOS Quick Action / Service that runs a shell script on the current active file from Finder or Obsidian.

### Setup
1. Open the **Shortcuts** app on your Mac.
2. Click the `+` icon to create a **New Shortcut**.
3. In the right panel, configure the shortcut settings:
   - Set **Use as Quick Action** to **True**.
   - Under **Services**, select **Finder** and **Obsidian** (or check *Provide Output* / *Run on Selected Files*).
4. Add the **Run Shell Script** action to the canvas.
5. Set the shell script fields:
   - **Shell:** `/bin/zsh`
   - **Pass Input:** `as arguments`
   - **Script:**
     ```bash
     for f in "$@"; do
       /path/to/vault-context-mcp/.venv/bin/vault-context mark-sensitive "$f"
     done
     ```
6. Save the Shortcut as `Mark Note Sensitive`.
7. Go to macOS **System Settings** > **Keyboard** > **Keyboard Shortcuts** > **Services**.
8. Find your shortcut `Mark Note Sensitive` under *General* or *Files and Folders* and assign a keyboard shortcut.
