"""OpenGL shaders for projection mapping renderer."""

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 in_pos;
layout(location = 1) in vec2 in_uv;

out vec2 v_uv;

uniform mat4 u_mvp;
uniform vec2 u_resolution;
uniform vec2 u_canvas_size;

void main() {
    // Convert from canvas coordinates to normalized device coordinates
    vec2 normalized = in_pos / u_canvas_size;
    vec2 ndc = normalized * 2.0 - 1.0;
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = in_uv;
}
"""

FRAGMENT_SHADER_TEXTURE = """
#version 330 core
in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform float u_opacity;
uniform float u_time;
uniform vec3 u_rgb_shift;  // (amount, speed, 0)

void main() {
    vec2 uv = v_uv;

    // RGB shift effect
    if (u_rgb_shift.x > 0.001) {
        float shift = u_rgb_shift.x * 0.01 * sin(u_time * u_rgb_shift.y);
        float r = texture(u_texture, uv + vec2(shift, 0.0)).r;
        float g = texture(u_texture, uv).g;
        float b = texture(u_texture, uv - vec2(shift, 0.0)).b;
        frag_color = vec4(r, g, b, u_opacity);
    } else {
        frag_color = texture(u_texture, uv) * u_opacity;
    }
}
"""

FRAGMENT_SHADER_SOLID = """
#version 330 core
out vec4 frag_color;

uniform vec4 u_color;
uniform float u_opacity;
uniform float u_time;
uniform vec3 u_rgb_shift;

void main() {
    vec4 color = u_color;

    // RGB shift effect
    if (u_rgb_shift.x > 0.001) {
        float shift = u_rgb_shift.x * sin(u_time * u_rgb_shift.y) * 0.1;
        color.r = clamp(color.r + shift, 0.0, 1.0);
        color.g = clamp(color.g - shift * 0.5, 0.0, 1.0);
        color.b = clamp(color.b + shift, 0.0, 1.0);
    }

    frag_color = vec4(color.rgb, color.a * u_opacity);
}
"""

FRAGMENT_SHADER_STROKE = """
#version 330 core
out vec4 frag_color;

uniform vec4 u_color;

void main() {
    frag_color = u_color;
}
"""

# Vertex data structure: x, y, u, v per vertex
VERTEX_FORMAT = "2f 2f"
VERTEX_STRIDE = 16  # 4 floats * 4 bytes
