// Runs the DraStic hook's fragment shaders offscreen (EGL surfaceless, Mesa llvmpipe)
// with the same quad/UV setup as run_shader_copy(), including the two-pass nitro-sharp.
// usage: gles_sim [-desktop] <shader|bilinear|nearest> in.ppm out.ppm [out_w out_h]
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "shaders.h"

typedef void *EGLDisplay, *EGLConfig, *EGLContext, *EGLSurface;
typedef int EGLint;
typedef unsigned int GLenum, GLuint;
typedef int GLint, GLsizei;
typedef float GLfloat;

static EGLDisplay (*eglGetPlatformDisplay)(GLenum, void *, const intptr_t *);
static int (*eglInitialize)(EGLDisplay, EGLint *, EGLint *);
static int (*eglBindAPI)(GLenum);
static int (*eglChooseConfig)(EGLDisplay, const EGLint *, EGLConfig *, EGLint, EGLint *);
static EGLContext (*eglCreateContext)(EGLDisplay, EGLConfig, EGLContext, const EGLint *);
static int (*eglMakeCurrent)(EGLDisplay, EGLSurface, EGLSurface, EGLContext);
static void *(*eglGetProcAddress)(const char *);

#define GLF(ret, name, args) static ret (*name) args;
#define GL_FUNCS \
    GLF(GLuint, glCreateShader, (GLenum)) \
    GLF(void, glShaderSource, (GLuint, GLsizei, const char *const *, const GLint *)) \
    GLF(void, glCompileShader, (GLuint)) \
    GLF(void, glGetShaderiv, (GLuint, GLenum, GLint *)) \
    GLF(void, glGetShaderInfoLog, (GLuint, GLsizei, GLsizei *, char *)) \
    GLF(GLuint, glCreateProgram, (void)) \
    GLF(void, glAttachShader, (GLuint, GLuint)) \
    GLF(void, glBindAttribLocation, (GLuint, GLuint, const char *)) \
    GLF(void, glLinkProgram, (GLuint)) \
    GLF(void, glGetProgramiv, (GLuint, GLenum, GLint *)) \
    GLF(void, glGetProgramInfoLog, (GLuint, GLsizei, GLsizei *, char *)) \
    GLF(GLint, glGetUniformLocation, (GLuint, const char *)) \
    GLF(void, glUniform1i, (GLint, GLint)) \
    GLF(void, glUniform2f, (GLint, GLfloat, GLfloat)) \
    GLF(void, glGenTextures, (GLsizei, GLuint *)) \
    GLF(void, glBindTexture, (GLenum, GLuint)) \
    GLF(void, glTexImage2D, (GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void *)) \
    GLF(void, glTexParameteri, (GLenum, GLenum, GLint)) \
    GLF(void, glPixelStorei, (GLenum, GLint)) \
    GLF(void, glGenFramebuffers, (GLsizei, GLuint *)) \
    GLF(void, glBindFramebuffer, (GLenum, GLuint)) \
    GLF(void, glFramebufferTexture2D, (GLenum, GLenum, GLenum, GLuint, GLint)) \
    GLF(GLenum, glCheckFramebufferStatus, (GLenum)) \
    GLF(void, glViewport, (GLint, GLint, GLsizei, GLsizei)) \
    GLF(void, glUseProgram, (GLuint)) \
    GLF(void, glEnableVertexAttribArray, (GLuint)) \
    GLF(void, glVertexAttribPointer, (GLuint, GLint, GLenum, unsigned char, GLsizei, const void *)) \
    GLF(void, glDrawArrays, (GLenum, GLint, GLsizei)) \
    GLF(void, glReadPixels, (GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void *)) \
    GLF(const unsigned char *, glGetString, (GLenum)) \
    GLF(void, glFinish, (void))
GL_FUNCS
#undef GLF

#define GL_TEXTURE_2D 0x0DE1
#define GL_FRAMEBUFFER 0x8D40
#define GL_NEAREST 0x2600
#define GL_LINEAR 0x2601

static const char FRAG_PLAIN[] =
    "#ifdef GL_ES\nprecision highp float;\n#endif\n"
    "varying vec2 v_texcoord;\nuniform sampler2D u_texture;\n"
    "void main() { gl_FragColor = SWIZ(texture2D(u_texture, v_texcoord)); }\n";

static unsigned char *read_ppm(const char *path, int *w, int *h) {
    FILE *f = fopen(path, "rb");
    if (!f || fscanf(f, "P6 %d %d 255", w, h) != 2) { fprintf(stderr, "bad ppm %s\n", path); exit(1); }
    fgetc(f);
    unsigned char *rgb = malloc(*w * *h * 3), *rgba = malloc(*w * *h * 4);
    if (fread(rgb, 3, *w * *h, f) != (size_t)(*w * *h)) { fprintf(stderr, "short ppm\n"); exit(1); }
    fclose(f);
    for (int i = 0; i < *w * *h; i++) {
        memcpy(rgba + 4 * i, rgb + 3 * i, 3);
        rgba[4 * i + 3] = 255;
    }
    free(rgb);
    return rgba;
}

static GLuint compile(GLenum type, const char *pre, const char *common, const char *src) {
    GLuint s = glCreateShader(type);
    const char *srcs[] = { pre, common, src };
    glShaderSource(s, 3, srcs, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, 0x8B81, &ok);
    if (!ok) {
        char log[4096];
        glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "compile failed:\n%s\n", log);
        exit(2);
    }
    return s;
}

static GLuint program(const char *pre, const char *common, const char *frag) {
    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile(0x8B31, pre, "", VERT_SRC));
    glAttachShader(prog, compile(0x8B30, pre, common, frag));
    glBindAttribLocation(prog, 0, "a_position");
    glBindAttribLocation(prog, 1, "a_texcoord");
    glLinkProgram(prog);
    GLint ok = 0;
    glGetProgramiv(prog, 0x8B82, &ok);
    if (!ok) { char log[4096]; glGetProgramInfoLog(prog, sizeof log, NULL, log); fprintf(stderr, "link: %s\n", log); exit(2); }
    return prog;
}

static GLuint texture(int w, int h, GLint filter, const void *pixels) {
    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, 0x1908, w, h, 0, 0x1908, 0x1401, pixels);
    glTexParameteri(GL_TEXTURE_2D, 0x2801, filter);
    glTexParameteri(GL_TEXTURE_2D, 0x2800, filter);
    glTexParameteri(GL_TEXTURE_2D, 0x2802, 0x812F);
    glTexParameteri(GL_TEXTURE_2D, 0x2803, 0x812F);
    return tex;
}

static GLuint framebuffer(GLuint tex) {
    GLuint fb;
    glGenFramebuffers(1, &fb);
    glBindFramebuffer(GL_FRAMEBUFFER, fb);
    glFramebufferTexture2D(GL_FRAMEBUFFER, 0x8CE0, GL_TEXTURE_2D, tex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != 0x8CD5) { fprintf(stderr, "fbo incomplete\n"); exit(1); }
    return fb;
}

// One pass like run_shader_copy(): quad over the viewport, texture on unit 0
static void draw(GLuint prog, GLuint src, GLuint fb, int vw, int vh,
                 float tw, float th, float ow, float oh, float sw, float sh, const GLfloat *verts) {
    glBindFramebuffer(GL_FRAMEBUFFER, fb);
    glBindTexture(GL_TEXTURE_2D, src);
    glViewport(0, 0, vw, vh);
    glUseProgram(prog);
    GLint l;
    glUniform1i(glGetUniformLocation(prog, "u_texture"), 0);
    if ((l = glGetUniformLocation(prog, "u_texture_size")) >= 0) glUniform2f(l, tw, th);
    if ((l = glGetUniformLocation(prog, "u_output_size")) >= 0) glUniform2f(l, ow, oh);
    if ((l = glGetUniformLocation(prog, "u_source_size")) >= 0) glUniform2f(l, sw, sh);
    glEnableVertexAttribArray(0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(0, 2, 0x1406, 0, 16, verts);
    glVertexAttribPointer(1, 2, 0x1406, 0, 16, verts + 2);
    glDrawArrays(0x0005, 0, 4);
}

int main(int argc, char **argv) {
    int desktop = 0;
    if (argc > 1 && !strcmp(argv[1], "-desktop")) { desktop = 1; argv++; argc--; }
    if (argc != 4 && argc != 6) {
        fprintf(stderr, "usage: gles_sim [-desktop] <shader|bilinear|nearest> in.ppm out.ppm [w h]\n");
        return 1;
    }
    const char *name = argv[1];
    int out_w = argc == 6 ? atoi(argv[4]) : 640, out_h = argc == 6 ? atoi(argv[5]) : 480;

    void *egl = dlopen("libEGL.so.1", RTLD_NOW);
    if (!egl) { fprintf(stderr, "%s\n", dlerror()); return 1; }
#define E(n) *(void **)&n = dlsym(egl, #n)
    E(eglGetPlatformDisplay); E(eglInitialize); E(eglBindAPI); E(eglChooseConfig);
    E(eglCreateContext); E(eglMakeCurrent); E(eglGetProcAddress);
    EGLDisplay dpy = eglGetPlatformDisplay(0x31DD /* SURFACELESS_MESA */, NULL, NULL);
    if (!dpy || !eglInitialize(dpy, NULL, NULL)) { fprintf(stderr, "eglInitialize failed\n"); return 1; }
    eglBindAPI(desktop ? 0x30A2 /* OPENGL_API */ : 0x30A0 /* OPENGL_ES_API */);
    EGLint cattr[] = { 0x3040 /* RENDERABLE_TYPE */, desktop ? 0x0008 : 0x0004, 0x3033 /* SURFACE_TYPE */, 0, 0x3038 };
    EGLConfig cfg; EGLint n = 0;
    if (!eglChooseConfig(dpy, cattr, &cfg, 1, &n) || n < 1) { fprintf(stderr, "no config\n"); return 1; }
    EGLint ctxattr[] = { 0x3098 /* CONTEXT_CLIENT_VERSION */, 2, 0x3038 };
    EGLContext ctx = eglCreateContext(dpy, cfg, NULL, desktop ? NULL : ctxattr);
    if (!ctx || !eglMakeCurrent(dpy, NULL, NULL, ctx)) { fprintf(stderr, "no context\n"); return 1; }
#define GLF(ret, n, args) *(void **)&n = eglGetProcAddress(#n);
    GL_FUNCS
#undef GLF

    // Same preambles as make_gl_program(); textures here are RGBA so SWIZ is identity
    const char *pre = desktop ? "#version 120\n#define SWIZ(c) (c)\n" : "#define SWIZ(c) (c)\n";
    const char *frag = NULL;
    GLint filter = GL_LINEAR; // SDL's default scale quality in DraStic
    int nitro = !strcmp(name, "nitro-sharp");
    if (!strcmp(name, "bilinear")) frag = FRAG_PLAIN;
    else if (!strcmp(name, "nearest")) { frag = FRAG_PLAIN; filter = GL_NEAREST; }
    else if (nitro) filter = GL_NEAREST; // mirrors shader_tex_filter
    else {
        for (size_t i = 0; i < sizeof FRAGS / sizeof FRAGS[0]; i++)
            if (!strcmp(FRAGS[i].name, name)) frag = *FRAGS[i].src;
    }
    if (!frag && !nitro) { fprintf(stderr, "unknown shader %s\n", name); return 1; }
    if (frag && desktop && !strncmp(frag, "precision mediump float;\n", 25)) frag += 25;

    int tw, th;
    unsigned char *img = read_ppm(argv[2], &tw, &th);
    glPixelStorei(0x0CF5, 1);
    GLuint src = texture(tw, th, filter, img);
    GLuint out = texture(out_w, out_h, GL_NEAREST, NULL);
    GLuint out_fb = framebuffer(out);

    // pos(x,y) | uv(u,v), V flipped like the hook's first quad; the second pass is unflipped
    static const GLfloat flipped[] = { -1, -1, 0, 1,   1, -1, 1, 1,   -1, 1, 0, 0,   1, 1, 1, 0 };
    static const GLfloat plain[]   = { -1, -1, 0, 0,   1, -1, 1, 0,   -1, 1, 0, 1,   1, 1, 1, 1 };

    if (nitro) {
        GLuint mid = texture(out_w, th, GL_NEAREST, NULL);
        GLuint mid_fb = framebuffer(mid);
        GLuint p1 = program(pre, NITRO_COMMON, FRAG_NITRO_H), p2 = program(pre, NITRO_COMMON, FRAG_NITRO_V);
        draw(p1, src, mid_fb, out_w, th, tw, th, out_w, th, tw, th, flipped);
        draw(p2, mid, out_fb, out_w, out_h, out_w, th, out_w, out_h, tw, th, plain);
    } else {
        draw(program(pre, "", frag), src, out_fb, out_w, out_h, tw, th, out_w, out_h, tw, th, flipped);
    }
    glFinish();

    unsigned char *px = malloc(out_w * out_h * 4);
    glPixelStorei(0x0D05, 1);
    glReadPixels(0, 0, out_w, out_h, 0x1908, 0x1401, px);
    FILE *f = fopen(argv[3], "wb");
    fprintf(f, "P6\n%d %d\n255\n", out_w, out_h);
    for (int y = out_h - 1; y >= 0; y--) // GL rows are bottom-up
        for (int x = 0; x < out_w; x++)
            fwrite(px + 4 * (y * out_w + x), 1, 3, f);
    fclose(f);
    fprintf(stderr, "%s: %s (%s) %dx%d -> %dx%d\n", name, glGetString(0x1F01),
            desktop ? "GL" : "GLES2", tw, th, out_w, out_h);
    return 0;
}
