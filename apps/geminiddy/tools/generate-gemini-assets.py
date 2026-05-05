import os
from PIL import Image, ImageDraw

# Generate Gemini-themed assets for Geminiddy
# 160x128 pixels (MiniToo size)
WIDTH, HEIGHT = 160, 128
ASSETS_DIR = "apps/geminiddy/assets"

def create_base_frame(bg_color=(10, 0, 30)):
    frame = Image.new("RGB", (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(frame)
    return frame, draw

def draw_star(draw, x, y, size, color):
    # Four-pointed star
    draw.line((x - size, y, x + size, y), fill=color, width=1)
    draw.line((x, y - size, x, y + size), fill=color, width=1)

def generate_chilling():
    frames = []
    for i in range(20):
        frame, draw = create_base_frame((15, 5, 40))
        # Static stars
        draw_star(draw, 30, 40, 2, (100, 100, 255))
        draw_star(draw, 120, 30, 1, (150, 150, 255))
        draw_star(draw, 50, 100, 1, (120, 120, 255))
        draw_star(draw, 140, 90, 2, (100, 100, 255))
        
        # Pulsing central star
        pulse = abs(10 - i) / 10.0 # 0.0 to 1.0
        size = 10 + int(pulse * 10)
        color = (150 + int(pulse * 105), 150 + int(pulse * 105), 255)
        draw_star(draw, WIDTH//2, HEIGHT//2, size, color)
        frames.append(frame)
    
    frames[0].save(os.path.join(ASSETS_DIR, "chilling.gif"), 
                   save_all=True, append_images=frames[1:], duration=100, loop=0)

def generate_working():
    frames = []
    for i in range(12):
        frame, draw = create_base_frame((20, 10, 60))
        # Twinkling background stars
        for s in range(5):
            sx, sy = (s * 30 + 20, (s * 23 + 15) % HEIGHT)
            twinkle = (i + s) % 3
            if twinkle > 0:
                draw_star(draw, sx, sy, twinkle, (200, 200, 255))
        
        # Central star "processing"
        angle = i * 30
        # Draw a rotating diamond
        points = [
            (WIDTH//2, HEIGHT//2 - 20 - i),
            (WIDTH//2 + 20 + i, HEIGHT//2),
            (WIDTH//2, HEIGHT//2 + 20 + i),
            (WIDTH//2 - 20 - i, HEIGHT//2)
        ]
        draw.polygon(points, outline=(180, 180, 255), fill=(40, 40, 100))
        draw_star(draw, WIDTH//2, HEIGHT//2, 5, (255, 255, 255))
        frames.append(frame)
    
    frames[0].save(os.path.join(ASSETS_DIR, "working.gif"), 
                   save_all=True, append_images=frames[1:], duration=80, loop=0)

def generate_alerting():
    frames = []
    for i in range(10):
        # Flashing background
        bg = (80, 20, 20) if i % 2 == 0 else (40, 10, 10)
        frame, draw = create_base_frame(bg)
        
        # Large amber pulsing star
        size = 25 if i % 2 == 0 else 15
        draw_star(draw, WIDTH//2, HEIGHT//2, size, (255, 200, 0))
        draw_star(draw, WIDTH//2, HEIGHT//2, size//2, (255, 255, 200))
        
        frames.append(frame)
    
    frames[0].save(os.path.join(ASSETS_DIR, "alerting.gif"), 
                   save_all=True, append_images=frames[1:], duration=150, loop=0)

if __name__ == "__main__":
    if not os.path.exists(ASSETS_DIR):
        os.makedirs(ASSETS_DIR)
    generate_chilling()
    generate_working()
    generate_alerting()
    print("Gemini assets generated in", ASSETS_DIR)
