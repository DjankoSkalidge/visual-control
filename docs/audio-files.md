# Audio files

An audio file, such as an mp3 of a song, plays through your speakers on a loop while its beat triggers [press effects](effects.md#press-effects-one-shot-animations). No MIDI file is needed: the app listens to the song itself and finds the hits.

## Set up an audio file

1. Drag an audio file onto the window: `.mp3`, `.wav`, `.flac`, `.ogg`, `.opus`, `.m4a` or `.aac`. You can drop it together with an image or video to open both.
2. The app analyses the song, which takes about half a second for a four-minute track, and a panel opens with three rows:

   | Band | Picks up |
   |---|---|
   | **Low** | Kick drums and bass |
   | **Mid** | Snares, claps, and other sounds in the middle, including vocals |
   | **High** | Hi-hats and cymbals |

3. Choose an effect for each band you want. Bands left on **None** do nothing.
4. Move a band's **Sensitivity** slider to change how many hits it finds. Left keeps only the strongest hits, right finds quieter ones too. The count next to it updates as you move it, with how many hits that is per second.
5. Click **Start**. The song plays from the beginning and loops until you remove it, drop another one or close the app.

While the panel is open, the video pauses, every effect turns off and controllers are ignored, as when [setting up a MIDI file](midi-files.md#set-up-a-midi-file). **Cancel** leaves things as they were, so a song that was already playing carries on.

## How hits are found

A hit is a sudden jump in loudness within one band. Because the whole song is analysed before it plays, every hit is known in advance, so effects land on the beat rather than just after it.

This works from the finished mix, so it isn't as exact as a MIDI file:

- **Kicks are found most reliably.** A heavy bass line can also count as hits in the low band.
- **Vocals and other instruments** can trigger the mid band, especially at high sensitivity.
- **Each band has at least 0.1 seconds between hits**, so one drum can't count twice. Very fast hi-hat rolls are thinned out.
- **Quiet parts of a song still get hits.** Each hit is compared with the hits in the few seconds around it, not with the loudest moment of the whole song.

If a band triggers too often, lower its sensitivity. If it misses hits you can hear, raise it.

## How the file is played

- **The sound is the clock.** Hits follow the position of the audio that's actually playing, so they stay in time with what you hear, loop after loop.
- **It plays independently of the video.** Pausing the video or changing its playback speed doesn't affect the song, and the song plays over still images and with nothing loaded at all.
- **It plays on your system's default sound output**, at full volume. Use your system's volume control.
- **A MIDI file can play at the same time**, each triggering its own effects.
- **Every hit plays its effect at full strength.**
- **If the app stalls**, the hits it missed are skipped instead of all playing at once.

> Assigning **flash** to a busy band, like high at high sensitivity, makes a fast strobe. Take care if an audience could include photosensitive people.

The status bar shows `Playing` and the file name while a song is playing. Only one audio file plays at a time.

To stop it, click **Remove audio file** in the status bar. Any black and white or removed color that the song left on turns off, but only for effects it was assigned.

Assignments and sensitivities aren't saved, so dropping the same file again starts over.

## Files that can't be used

The status bar names the file and the problem, and nothing changes. A song that's already playing keeps playing.

| Message | Cause |
|---|---|
| `is silent` | The file has no sound |
| `can't read it as an audio file` | The file is damaged, or isn't an audio file |
| `is too short to loop` | The file lasts less than about 50 ms |

If a song stops with `Stopped playing` in the status bar, the sound system reported a problem, such as the output device being unplugged.
