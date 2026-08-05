"""OpenGL shaders for projection mapping renderer."""

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 in_pos;
layout(location = 1) in vec2 in_uv;

out vec2 v_uv;
out vec2 v_pos;

uniform mat4 u_mvp;
uniform vec2 u_resolution;
uniform vec2 u_canvas_size;

void main() {
    // Convert from canvas coordinates to normalized device coordinates.
    // Canvas Y grows downward (top-left origin, matching the editor) while
    // NDC Y grows upward, so Y is inverted here - without it the projection
    // comes out mirrored vertically against what the editor shows.
    vec2 normalized = in_pos / u_canvas_size;
    vec2 ndc = vec2(normalized.x * 2.0 - 1.0, 1.0 - normalized.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = in_uv;
    // Canvas-space position, needed by the projective UV path in the fragment
    // stage. Interpolating it linearly is exact here: the projection is
    // orthographic and every shape is flat.
    v_pos = in_pos;
}
"""

FRAGMENT_SHADER_TEXTURE = """
#version 330 core
in vec2 v_uv;
in vec2 v_pos;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform float u_opacity;
uniform float u_time;
uniform vec3 u_rgb_shift;  // (amount, speed, 0)
uniform mat3 u_uv_matrix;      // canvas -> UV homography (corner pin)
uniform int u_uv_projective;   // 0 = per-vertex v_uv, 1 = u_uv_matrix
uniform vec2 u_media_offset;   // shift in UV units
uniform float u_media_rotation; // radians, about the media centre
uniform int u_uv_clip;         // 1 = drop samples outside the media
uniform vec4 u_source_rect;    // (u0, v0, width, height) of the input region

// Slack on the clip test. The corner-pin divide can land a hair outside the
// unit square right on a quad's edge, and clipping that strictly would cut a
// transparent hairline along every corner-pinned surface.
const float UV_CLIP_EPS = 0.001;

void main() {
    vec2 uv = v_uv;

    // Corner pin: dividing by the homogeneous component per fragment is what
    // makes the media follow the surface in perspective. Interpolating UVs
    // per vertex instead bends the image along the triangulation diagonal.
    if (u_uv_projective == 1) {
        vec3 h = u_uv_matrix * vec3(v_pos, 1.0);
        if (abs(h.z) > 1e-9) {
            uv = h.xy / h.z;
        }
    }

    // Media transform: rotate about the media's centre, then pan. Applied
    // after the surface mapping so it repositions the content within the
    // surface rather than moving the surface itself.
    if (u_media_rotation != 0.0) {
        float c = cos(u_media_rotation);
        float s = sin(u_media_rotation);
        vec2 centred = uv - 0.5;
        uv = vec2(centred.x * c - centred.y * s, centred.x * s + centred.y * c) + 0.5;
    }
    uv -= u_media_offset;

    // Anything outside the media is genuinely empty - the bars of a `contain`
    // fit, or the gap revealed by panning. Discarding beats clamping, which
    // would smear the edge row of pixels across them.
    if (u_uv_clip == 1 &&
        (uv.x < -UV_CLIP_EPS || uv.x > 1.0 + UV_CLIP_EPS ||
         uv.y < -UV_CLIP_EPS || uv.y > 1.0 + UV_CLIP_EPS)) {
        discard;
    }

    // Input space last: everything above decides where in the *surface* this
    // fragment falls, and this maps that onto the chosen region of the media.
    // Clipping happens before the remap, so the test stays against the plain
    // unit square whatever region is selected.
    uv = u_source_rect.xy + uv * u_source_rect.zw;

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
