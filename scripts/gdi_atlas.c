/* Private exact GDI atlas; original fonts only. No Civ2/observer use. */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#define W 512
#define H 240
static unsigned char pixels[(W/8)*H];
static struct {BITMAPINFOHEADER h;RGBQUAD colors[2];} info;
static int render_atlas(int weight,const char *bitmap_path,const char *metrics_path){
 HDC screen,dc;HBITMAP bm,oldbm;HFONT font,oldfont;TEXTMETRIC tm;BITMAPFILEHEADER file;FILE *out,*meta;char ch;int code,x,y,got;DWORD ext;
 screen=GetDC(NULL);dc=CreateCompatibleDC(screen);bm=CreateCompatibleBitmap(screen,W,H);oldbm=SelectObject(dc,bm);
 font=CreateFont(-16,0,0,0,weight,0,0,0,ANSI_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,DEFAULT_QUALITY,DEFAULT_PITCH,"Times New Roman");oldfont=SelectObject(dc,font);
 PatBlt(dc,0,0,W,H,WHITENESS);SetTextColor(dc,RGB(0,0,0));SetBkColor(dc,RGB(255,255,255));SetBkMode(dc,OPAQUE);GetTextMetrics(dc,&tm);
 meta=fopen(metrics_path,"wt");if(!meta)return 2;
 fprintf(meta,"code\tcell_x\tcell_y\torigin_x\torigin_y\tadvance\theight\n");
 for(code=32;code<=126;code++){ch=(char)code;x=((code-32)%16)*32;y=((code-32)/16)*40;TextOut(dc,x+4,y+4,&ch,1);ext=GetTextExtent(dc,&ch,1);fprintf(meta,"%d\t%d\t%d\t%d\t%d\t%d\t%d\n",code,x,y,x+4,y+4,(int)LOWORD(ext),(int)HIWORD(ext));}fclose(meta);
 SelectObject(dc,oldfont);SelectObject(dc,oldbm);memset(&info,0,sizeof(info));info.h.biSize=sizeof(BITMAPINFOHEADER);info.h.biWidth=W;info.h.biHeight=H;info.h.biPlanes=1;info.h.biBitCount=1;info.h.biCompression=BI_RGB;info.h.biSizeImage=sizeof(pixels);info.h.biClrUsed=2;info.colors[1].rgbRed=info.colors[1].rgbGreen=info.colors[1].rgbBlue=255;
 got=GetDIBits(screen,bm,0,H,pixels,(BITMAPINFO FAR *)&info,DIB_RGB_COLORS);
 if(got){memset(&file,0,sizeof(file));file.bfType=0x4d42;file.bfOffBits=sizeof(file)+sizeof(info);file.bfSize=file.bfOffBits+sizeof(pixels);out=fopen(bitmap_path,"wb");if(out){fwrite(&file,sizeof(file),1,out);fwrite(&info,sizeof(info),1,out);fwrite(pixels,sizeof(pixels),1,out);fclose(out);}}
 DeleteObject(font);DeleteObject(bm);DeleteDC(dc);ReleaseDC(NULL,screen);return got==H?0:3;
}
int PASCAL WinMain(HINSTANCE inst,HINSTANCE prev,LPSTR cmd,int show){
 FILE *out;int a,b;
 a=render_atlas(700,"C:\\ATLAS.BMP","C:\\GLYPHS.TSV");
 b=render_atlas(400,"C:\\ATREG.BMP","C:\\REGULAR.TSV");
 if(a||b)return 2;
 out=fopen("C:\\ATDONE.TXT","wt");if(out){fprintf(out,"complete bold and regular\n");fclose(out);}return 0;
}
