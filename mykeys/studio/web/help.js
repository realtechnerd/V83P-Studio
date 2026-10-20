// "?" help for each page. Plain data: [heading, [lines]] sections. Shown by showHelp() in app.js.
"use strict";
const HELP = {
  lighting: {
    title: "Lighting",
    intro: "Set what every key on your keyboard looks like.",
    sections: [
      ["Pick keys", [
        "Click a key to select it. Shift or Ctrl + click adds more keys, and dragging draws a box around several.",
        "The buttons above the keyboard (WASD, Arrows, Letters…) select common groups in one click.",
        "With nothing selected, your changes apply to the whole keyboard. Esc or a click on empty space clears the selection.",
      ]],
      ["Choose what they do", [
        "Static: one color that stays on. Choose it with the color wheel, the swatches or a hex code.",
        "Animated: the key follows the animation. All animated keys share one animation, chosen below the color wheel.",
        "Off: the key stays dark.",
        "You can mix them: for example, static WASD, everything else animated.",
      ]],
      ["Keep it", [
        "Changes show on the keyboard right away but are temporary until you click Save to keyboard. A dot on the button means there are unsaved changes.",
        "Saved lighting stays after unplugging and also works on 2.4G and Bluetooth.",
        "Reset sets keys back to animated.",
      ]],
      ["Good to know", [
        "Editing needs the cable, with the switch on wired.",
        "Brightness at the top dims or brightens everything at once. Key brightness only affects the selected static keys.",
      ]],
    ],
  },
  keys: {
    title: "Keys",
    intro: "Change what each key types.",
    sections: [
      ["Remap a key", [
        "Choose a layer at the top, click a key on the drawing, then choose its new function in the list below. Use the search box to find one fast.",
        "Changes are written to the keyboard instantly and work wired and wireless.",
      ]],
      ["Layers", [
        "The keyboard has four layers: Windows, Windows + Fn, Mac and Mac + Fn. The Fn layers are what keys do while you hold Fn.",
        "Most people only change the Windows layer, plus the Windows Fn layer for shortcuts.",
      ]],
      ["Shortcuts and modifiers", [
        "Use the \"Hold with\" buttons (Ctrl, Shift, Alt, Win) above the list to make one key send a combination, like Ctrl + C.",
      ]],
      ["Undo", [
        "Reload from keyboard shows what is really on the keyboard. To go back to factory keys, hold Fn + Esc for 3 seconds. That resets all settings, not just keys.",
      ]],
    ],
  },
  macros: {
    title: "Macros",
    intro: "Make one key type text or play a sequence of keys.",
    sections: [
      ["Make a macro", [
        "Choose a slot on the left and give it a name.",
        "Add steps: + Text types a phrase, + Key presses one key, + Shortcut presses a combination, and + Delay waits.",
        "Or click Record and type in this window. It captures presses, releases and pauses.",
        "Click Save macros to store them on the keyboard.",
      ]],
      ["Put it on a key", [
        "Under Assign to, choose a layer, then click the key that should play the macro.",
      ]],
      ["Good to know", [
        "Macros live on the keyboard, so they work wired and wireless and on any computer.",
        "There are 16 slots that share a small amount of memory. The bar at the top shows how much is used.",
      ]],
    ],
  },
  knob: {
    title: "Knob",
    intro: "Choose what turning and pressing the knob does.",
    sections: [
      ["Change it", [
        "Each layer has three actions: turn left, turn right and press. Click one and choose a new function.",
        "Volume and media keys are the usual choice. Brightness, scrolling or any normal key work too.",
      ]],
      ["Volume display", [
        "When the volume changes, the whole keyboard turns into a volume meter for a moment, filling from left to right, then fades back to your lighting.",
        "Bar color: Auto picks your keyboard's accent color, or a contrasting one if your lighting is already close to it. Green → red changes with the level; Custom is any color you pick.",
        "Muted shows as a dim red bar. Preview shows it at the current volume.",
        "It needs the V83P Studio firmware and the cable. With music mode playing, the meter is drawn over the music.",
      ]],
      ["Good to know", [
        "Knob changes are saved on the keyboard instantly and work wireless too.",
      ]],
    ],
  },
  music: {
    title: "Music",
    intro: "Make the keyboard react to the music you're playing.",
    sections: [
      ["Turn it on", [
        "Flip the switch at the top right, then play something in Spotify on this PC.",
        "It takes over the lighting while music plays and gives it back after about 8 seconds of silence.",
      ]],
      ["Make it yours", [
        "Style: how the music is shown. Try a few with a song you know well.",
        "Palette: the colors used. Album art takes the colors from the current song's cover.",
        "Sensitivity: how strongly it reacts. Smoothing: higher is calmer, lower is snappier.",
        "Dynamics: low makes every song fill the keyboard, high keeps quiet parts dim so drops hit harder.",
        "Only when Spotify is playing: turn off to react to any sound on the PC (games, YouTube…).",
      ]],
      ["Good to know", [
        "Music mode needs the cable (wired). On 2.4G or Bluetooth it waits and picks up again when you plug in.",
        "Your normal lighting comes back by itself when the music stops or you turn music mode off.",
      ]],
    ],
  },
  reactions: {
    title: "Reactions",
    intro: "Light up the keyboard when something happens on your PC.",
    sections: [
      ["Make a reaction", [
        "Click New reaction and give it a name.",
        "When: add one or more apps. Pick from the list, type a name like \"Steam\", or click Browse… to choose any program in File Explorer.",
        "Choose \"launches\" for a loading animation that plays while the app starts and stops when its window appears. Tick \"flash green when loaded\" for a signal when it's ready.",
        "Or choose \"is the active window\" for lighting that stays while you're using that app.",
        "Play: choose an animation, a color pulse or flash, a rainbow, or a steady scene. Then click Save.",
      ]],
      ["Good to know", [
        "Reactions run while the cable is connected and V83P Studio is open (it can stay in the tray).",
        "Apps that were already open when V83P Studio started don't count as launches. Close and reopen them to test.",
        "When a reaction ends, the keyboard goes back to your Lighting page setup.",
        "Pause them any time from the tray icon menu.",
        "Games from Steam often don't appear in the list. Use Browse… and choose the game's .exe in its folder.",
      ]],
    ],
  },
  profiles: {
    title: "Profiles",
    intro: "Save your whole setup and switch between setups.",
    sections: [
      ["Save and load", [
        "Type a name and click Save current. That stores the lighting, key colors, keymap, knob and macros.",
        "Apply loads a saved profile back onto the keyboard. Overwrite replaces it with your current setup.",
      ]],
      ["Automatic switching", [
        "Change the lighting depending on which app you're using, for example a red scheme while a game is open.",
        "Add app rule: choose apps (from the list, by name, or with Browse…) and the profile to use while one of them is focused.",
        "Otherwise: the profile to use for every other app. Turn on the switch and click Save.",
        "Only lighting and key colors switch automatically, never keys or macros, and it doesn't wear the keyboard's memory.",
      ]],
      ["Good to know", [
        "Automatic switching needs the cable and V83P Studio running (it can stay in the tray).",
        "You can also switch profiles from the tray icon menu.",
      ]],
    ],
  },
  device: {
    title: "Device",
    intro: "Connection, firmware and app settings.",
    sections: [
      ["Look", [
        "Keyboard colorway: choose Matcha or Mint so the app draws your keyboard correctly and uses matching colors.",
        "Appearance: dark, light, or follow Windows.",
      ]],
      ["Wired vs wireless", [
        "Editing anything needs the cable, with the switch on the back set to wired.",
        "Everything you've saved (lighting, keys, macros, knob) keeps working on 2.4G and Bluetooth.",
        "Live features (music, reactions, automatic profiles) need the cable while they run.",
      ]],
      ["Firmware", [
        "Per-key colors, music mode and reactions need the V83P Studio firmware. Install it from the Firmware card: the app walks you through it.",
        "The first install backs up your keyboard's original firmware and resets its settings. Updates after that keep your settings.",
        "Restore a backup puts the original firmware back at any time.",
      ]],
      ["Keyboard shortcuts", [
        "Fn + 1 / 2 / 3: Bluetooth devices (hold 3 seconds to pair). Fn + 4: 2.4G. Fn + 5: USB.",
        "Fn + Esc for 3 seconds: reset everything to factory settings.",
      ]],
    ],
  },
};
