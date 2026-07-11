import os
from PIL import Image, ImageDraw

def generate_debug_sprite_sheet():
    # Frame configurations
    frame_w = 128
    frame_h = 128
    cols = 10
    rows = 6
    sheet_w = frame_w * cols
    sheet_h = frame_h * rows

    # Row metadata
    row_meta = [
        {"name": "Idle", "bg": (200, 230, 255, 255), "body": (50, 120, 240, 255)},     # Blueish
        {"name": "Walk", "bg": (210, 255, 210, 255), "body": (40, 180, 90, 255)},      # Greenish
        {"name": "Wave", "bg": (255, 230, 200, 255), "body": (240, 130, 40, 255)},     # Orangey
        {"name": "Jump", "bg": (255, 210, 210, 255), "body": (220, 60, 60, 255)},      # Reddish
        {"name": "Think", "bg": (255, 255, 200, 255), "body": (210, 180, 30, 255)},    # Yellowish
        {"name": "Talk", "bg": (240, 210, 255, 255), "body": (160, 80, 220, 255)}      # Purpleish
    ]

    # Create transparent image
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)

    for row_idx, meta in enumerate(row_meta):
        name = meta["name"]
        bg_col = meta["bg"]
        body_col = meta["body"]
        
        y_offset = row_idx * frame_h
        
        for col_idx in range(cols):
            x_offset = col_idx * frame_w
            
            # Draw frame boundary border (subtle) for debugging alignments
            draw.rectangle(
                [x_offset, y_offset, x_offset + frame_w - 1, y_offset + frame_h - 1],
                outline=(180, 180, 180, 100), width=1
            )
            
            # Calculate coordinates for drawing the pet body inside the frame
            # Default center: (x_offset + 64, y_offset + 64)
            cx, cy = x_offset + 64, y_offset + 64
            r = 30
            
            # Squish or stretch based on state/frame to simulate animation
            rx, ry = r, r
            cy_adjust = 0
            
            # 1. State-specific body modifications
            if name == "Jump":
                if col_idx in [0, 1]:  # Crouch
                    ry = 20
                    rx = 36
                    cy_adjust = 10
                elif col_idx == 2:     # Launch
                    ry = 38
                    rx = 24
                    cy_adjust = -5
                elif col_idx in [3, 4, 5]: # Fall/Fly
                    ry = 30
                    rx = 30
                    cy_adjust = -15
                elif col_idx in [6, 7, 8, 9]: # Landing
                    ry = 18
                    rx = 38
                    cy_adjust = 12
            elif name == "Walk":
                # Bounce up and down
                cy_adjust = -4 if col_idx % 2 == 0 else 2
            
            # Draw pet body
            draw.ellipse(
                [cx - rx, cy - ry + cy_adjust, cx + rx, cy + ry + cy_adjust],
                fill=body_col, outline=(30, 30, 30, 255), width=2
            )
            
            # Draw eyes
            eye_y = cy - 10 + cy_adjust
            # Blinking logic for idle
            is_blinking = (name == "Idle" and col_idx in [4, 5])
            
            if is_blinking:
                # Closed eyes (horizontal lines)
                draw.line([cx - 15, eye_y, cx - 5, eye_y], fill=(0, 0, 0, 255), width=2)
                draw.line([cx + 5, eye_y, cx + 15, eye_y], fill=(0, 0, 0, 255), width=2)
            else:
                # Open eyes
                draw.ellipse([cx - 14, eye_y - 4, cx - 6, eye_y + 4], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=1)
                draw.ellipse([cx + 6, eye_y - 4, cx + 14, eye_y + 4], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=1)
                # Pupils looking forward/right
                draw.ellipse([cx - 11, eye_y - 2, cx - 8, eye_y + 2], fill=(0, 0, 0, 255))
                draw.ellipse([cx + 9, eye_y - 2, cx + 12, eye_y + 2], fill=(0, 0, 0, 255))
                
            # Draw mouth
            mouth_y = cy + 8 + cy_adjust
            if name == "Talk":
                # Open and close mouth
                mouth_r = 6 if col_idx % 2 == 0 else 2
                draw.ellipse([cx - mouth_r, mouth_y - mouth_r, cx + mouth_r, mouth_y + mouth_r], fill=(200, 50, 50, 255), outline=(0, 0, 0, 255), width=1)
            elif name == "Think":
                # Curved thinking line
                draw.arc([cx - 8, mouth_y - 4, cx + 8, mouth_y + 4], start=0, end=180, fill=(0, 0, 0, 255), width=2)
            else:
                # Simple smile
                draw.arc([cx - 8, mouth_y - 5, cx + 8, mouth_y + 3], start=0, end=180, fill=(0, 0, 0, 255), width=2)

            # Draw state-specific arm/foot details
            if name == "Wave":
                # Wave hand up and down
                hand_wave_y = cy - 20 if col_idx % 2 == 0 else cy - 5
                draw.line([cx + 25, cy, cx + 38, hand_wave_y], fill=(0, 0, 0, 255), width=3)
                draw.ellipse([cx + 34, hand_wave_y - 4, cx + 42, hand_wave_y + 4], fill=body_col, outline=(0, 0, 0, 255))
            elif name == "Walk":
                # Feet moving
                foot_l_y = cy + ry + cy_adjust
                foot_r_y = cy + ry + cy_adjust
                if col_idx % 2 == 0:
                    foot_l_y -= 6
                else:
                    foot_r_y -= 6
                draw.ellipse([cx - 20, foot_l_y - 4, cx - 8, foot_l_y + 4], fill=(50, 50, 50, 255), outline=(0, 0, 0, 255))
                draw.ellipse([cx + 8, foot_r_y - 4, cx + 20, foot_r_y + 4], fill=(50, 50, 50, 255), outline=(0, 0, 0, 255))
            else:
                # Static small feet
                draw.ellipse([cx - 16, cy + ry - 2 + cy_adjust, cx - 4, cy + ry + 4 + cy_adjust], fill=(50, 50, 50, 255), outline=(0, 0, 0, 255))
                draw.ellipse([cx + 4, cy + ry - 2 + cy_adjust, cx + 16, cy + ry + 4 + cy_adjust], fill=(50, 50, 50, 255), outline=(0, 0, 0, 255))

            # Draw text label inside frame
            text = f"{name} {col_idx}"
            draw.text((x_offset + 5, y_offset + 5), text, fill=(0, 0, 0, 180))

    # Save sprite sheet
    os.makedirs("assets/sprites/default", exist_ok=True)
    sheet.save("assets/sprites/default/sprite_sheet.png")
    print("Debug sprite sheet generated successfully at assets/sprites/default/sprite_sheet.png")

if __name__ == "__main__":
    generate_debug_sprite_sheet()
