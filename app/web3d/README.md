# 3D live page
Stack suggestion: Vite + Three.js. 3D pitch, 22 animated players (interpolated between 1 Hz ticks),
ball, scoreboard, side panel with live distance/sprints/max speed, camera presets.
Connects to `ws://localhost:8000/ws/live`. Replay speed control sends a command to the producer.
