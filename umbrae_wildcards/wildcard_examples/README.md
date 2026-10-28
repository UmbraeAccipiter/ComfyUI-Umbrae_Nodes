# umbrae_nodes wildcard_examples

Wildcards shipped WITH the pack: the aspect defaults plus small SFW examples of
the processor's syntax. This folder is the LOWEST-priority wildcard source:

  1. umbrae_nodes/wildcards/            (your files - never shipped, never overwritten)
  2. Impact Pack's custom wildcards folder
  3. umbrae_nodes/wildcard_examples/    (this folder - replaced on every update)

To change any of these, copy the file into umbrae_nodes/wildcards/ under the
same relative path (e.g. wildcards/aspect/vertical.txt) and edit the copy. The
copy wins, and pack updates will not touch it. Do not edit the files here: an
update overwrites them. Press "Refresh Wildcards" on the node after copying.

  aspect/horizontal.txt, vertical.txt, square.txt
      inserted by [[aspect]] in a prompt: one random line, picked by the
      orientation of the latent / width / height connected to the node
  example/*.txt, emotions.txt
      syntax demonstrations; see umbrae_wildcard_syntax.md
  example/portrait/  (v0.8.8)
      relative tags and folder calls: __example/portrait/portrait__ uses
      __./face__ (file next to it), __./outfit/__ (every file in a folder
      next to it) and __../scene__ (one folder up). Rename or move the
      portrait/ folder and it still works.
  example/story.txt  (v0.8.8)
      a file that calls itself (__./story__); the recursion guard stops it
      repeating a line, so it always ends.
