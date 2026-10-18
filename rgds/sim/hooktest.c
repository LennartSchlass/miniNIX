// Drives the DraStic hook (LD_PRELOAD) through SDL2 like DraStic does: two 256x192
// streaming screens copied onto the window, a few frames, then the window is read back.
// usage: hooktest pattern.ppm out.ppm
#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>

static Uint32 *load(const char *path, int *w, int *h) {
    FILE *f = fopen(path, "rb");
    if (!f || fscanf(f, "P6 %d %d 255", w, h) != 2) { fprintf(stderr, "bad ppm\n"); exit(1); }
    fgetc(f);
    Uint32 *px = malloc(*w * *h * 4);
    for (int i = 0; i < *w * *h; i++) {
        int r = fgetc(f), g = fgetc(f), b = fgetc(f);
        px[i] = 0xFF000000u | r << 16 | g << 8 | b;   /* ARGB8888 */
    }
    fclose(f);
    return px;
}

int main(int argc, char **argv) {
    if (argc != 3) return 1;
    if (SDL_Init(SDL_INIT_VIDEO) != 0) { fprintf(stderr, "init: %s\n", SDL_GetError()); return 1; }
    SDL_SetHint(SDL_HINT_RENDER_DRIVER, "opengles2");
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");   /* like DraStic */
    SDL_Window *win = SDL_CreateWindow("drastic", 0, 0, 256, 192, SDL_WINDOW_OPENGL);
    if (!win) { fprintf(stderr, "window: %s\n", SDL_GetError()); return 1; }
    SDL_Renderer *r = SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED);
    if (!r) { fprintf(stderr, "renderer: %s\n", SDL_GetError()); return 1; }
    SDL_RendererInfo info;
    SDL_GetRendererInfo(r, &info);
    int ww, wh, ow, oh;
    SDL_GetWindowSize(win, &ww, &wh);
    SDL_GetRendererOutputSize(r, &ow, &oh);
    fprintf(stderr, "renderer %s, window %dx%d, output %dx%d\n", info.name, ww, wh, ow, oh);

    int w, h;
    Uint32 *px = load(argv[1], &w, &h);
    SDL_Texture *scr[2], *stylus;
    for (int i = 0; i < 2; i++) {
        scr[i] = SDL_CreateTexture(r, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, w, h);
        SDL_UpdateTexture(scr[i], NULL, px, w * 4);
    }
    stylus = SDL_CreateTexture(r, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STATIC, 32, 32);
    SDL_Rect a = { 0, 0, 640, 480 }, b = { 640, 0, 384, 288 }, s = { 700, 500, 32, 32 };
    for (int frame = 0; frame < 3; frame++) {
        SDL_SetRenderDrawColor(r, 20, 20, 20, 255);
        SDL_RenderClear(r);
        SDL_RenderCopy(r, scr[0], NULL, &a);
        SDL_RenderCopy(r, scr[1], NULL, &b);
        SDL_RenderCopy(r, stylus, NULL, &s);
        SDL_RenderPresent(r);
    }
    SDL_SetRenderDrawColor(r, 20, 20, 20, 255);
    SDL_RenderClear(r);
    SDL_RenderCopy(r, scr[0], NULL, &a);
    SDL_RenderCopy(r, scr[1], NULL, &b);
    SDL_RenderCopy(r, stylus, NULL, &s);
    unsigned char *out = malloc(ow * oh * 3);
    if (SDL_RenderReadPixels(r, NULL, SDL_PIXELFORMAT_RGB24, out, ow * 3) != 0) {
        fprintf(stderr, "readback: %s\n", SDL_GetError());
        return 1;
    }
    FILE *f = fopen(argv[2], "wb");
    fprintf(f, "P6\n%d %d\n255\n", ow, oh);
    fwrite(out, 3, ow * oh, f);
    fclose(f);
    SDL_Quit();
    return 0;
}
