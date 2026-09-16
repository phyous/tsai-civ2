/* Read-only observer for the pinned original Civ II1.06 Win16 executable.
 * USER metadata + ToolHelp MemoryRead only. Fixed regions come from its
 * original save serializer. No setters, hooks, arbitrary address requests,
 * game-file writes, or strategy. OBSREQ/OBSRESP are observer-owned files. */
#include <windows.h>
#include <toolhelp.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdlib.h>
#define MAXBUF 24000
static HINSTANCE instance;
static HWND root,active;
static HTASK gameTask;
static char body[MAXBUF],lastNonce[33];
static unsigned used,count,roots,overflow,above;
static void add(const char *format,...) {
 char part[600];va_list ap;unsigned n;
 va_start(ap,format);vsprintf(part,format,ap);va_end(ap);n=strlen(part);
 if(used+n>=MAXBUF-1){overflow=1;return;}memcpy(body+used,part,n);used+=n;body[used]=0;
}
static void quote(const char *s){unsigned char c;add("\"");while((c=(unsigned char)*s++)!=0){if(c=='\"'||c=='\\')add("\\%c",c);else if(c<32||c>126)add("\\u%04x",(unsigned)c);else add("%c",c);}add("\"");}
static int intersects(RECT r){return r.left<640&&r.top<480&&r.right>0&&r.bottom>0;}
static int belongs(HWND h){unsigned i;for(i=0;h&&i<16;i++){if(h==root)return 1;h=GetParent(h);}return 0;}
static int visibleCenter(HWND h,RECT r){POINT p;HWND hit;
 if(!intersects(r))return 0;p.x=max(0,min(639,(r.left+r.right)/2));p.y=max(0,min(479,(r.top+r.bottom)/2));hit=WindowFromPoint(p);return hit==h||IsChild(h,hit);}
BOOL FAR PASCAL __export findRoot(HWND h,LPARAM unused){char path[160],title[96];HINSTANCE app;
 if(!IsWindowVisible(h))return 1;app=(HINSTANCE)GetWindowWord(h,GWW_HINSTANCE);path[0]=title[0]=0;GetModuleFileName(app,path,sizeof(path));strupr(path);
 if(strstr(path,"CIV2.EXE")==NULL)return 1;GetWindowText(h,title,sizeof(title));
 if(!lstrcmp(title,"Sid Meier's Civilization II")){root=h;gameTask=GetWindowTask(h);roots++;}return 1;}
static void emit(HWND h,int top,int foreign){RECT r;char cls[80],caption[96];int center;
 if(!IsWindowVisible(h))return;GetWindowRect(h,&r);if(!intersects(r))return;
 if(count>=96){overflow=1;return;}GetClassName(h,cls,sizeof(cls));center=visibleCenter(h,r);caption[0]=0;
 if(!foreign&&(center||h==active))GetWindowText(h,caption,sizeof(caption));
 if(count++)add(",");add("{\"hwnd\":%u,\"parent\":%u,\"owner\":%u,\"task\":%u,\"top\":%d,\"foreign_above_root\":%d,\"root_related\":%d,\"enabled\":%d,\"style\":%lu,\"center_exposed\":%d,\"rect\":[%d,%d,%d,%d],\"class\":",(unsigned)h,(unsigned)GetParent(h),(unsigned)GetWindow(h,GW_OWNER),(unsigned)GetWindowTask(h),top,foreign,belongs(h),IsWindowEnabled(h)?1:0,(unsigned long)GetWindowLong(h,GWL_STYLE),center,r.left,r.top,r.right,r.bottom);quote(cls);add(",\"caption\":");quote(caption);add("}");
}
BOOL FAR PASCAL __export children(HWND h,LPARAM unused){emit(h,0,0);return !overflow;}
BOOL FAR PASCAL __export tops(HWND h,LPARAM unused){FARPROC cb;
 if(h==root)above=0;
 if(GetWindowTask(h)==gameTask){emit(h,1,0);if(IsWindowVisible(h)){cb=MakeProcInstance((FARPROC)children,instance);EnumChildWindows(h,(WNDENUMPROC)cb,0L);FreeProcInstance(cb);}}
 else if(above&&IsWindowVisible(h))emit(h,1,1);
 return !overflow;
}
static void sample(const char *nonce){FARPROC cb;unsigned i,j;POINT pt;HWND hit;DWORD ticks=GetTickCount();
 used=count=roots=overflow=0;root=0;gameTask=0;active=GetActiveWindow();
 cb=MakeProcInstance((FARPROC)findRoot,instance);EnumWindows((WNDENUMPROC)cb,0L);FreeProcInstance(cb);
 add("{\"version\":1,\"nonce\":\"%s\",\"ticks\":%lu,\"active\":%u,\"active_task\":%u,\"root\":%u,\"root_count\":%u,\"game_task\":%u,\"status\":",nonce,ticks,(unsigned)active,(unsigned)GetWindowTask(active),(unsigned)root,roots,(unsigned)gameTask);
 if(roots!=1||!active||GetWindowTask(active)!=gameTask){quote("unknown_foreground");add(",\"windows\":[],\"hit_grid\":[],\"stable_active\":false}");return;}
 quote("observed");add(",\"windows\":[");above=1;cb=MakeProcInstance((FARPROC)tops,instance);EnumWindows((WNDENUMPROC)cb,0L);FreeProcInstance(cb);
 add("],\"hit_grid\":[");for(j=0;j<7;j++){pt.y=44+j*70;if(pt.y>479)pt.y=479;for(i=0;i<9;i++){pt.x=16+i*76;if(pt.x>639)pt.x=639;hit=WindowFromPoint(pt);if(i||j)add(",");add("[%d,%d,%u,%u]",pt.x,pt.y,(unsigned)hit,(unsigned)GetWindowTask(hit));}}
 add("],\"stable_active\":%s,\"overflow\":%s}",active==GetActiveWindow()?"true":"false",overflow?"true":"false");
}

static unsigned char chunk[1024];
static unsigned long outputSize,outputHash;
static int writeBytes(FILE*f,const void *p,unsigned n){unsigned i;const unsigned char*b=p;
 if(fwrite(p,1,n,f)!=n)return 0;for(i=0;i<n;i++){outputHash^=b[i];outputHash*=16777619UL;}outputSize+=n;return 1;
}
static int readRegion(FILE*f,unsigned selector,unsigned long offset,unsigned long size){unsigned n;unsigned long at;
 for(at=0;at<size;at+=n){n=(unsigned)min(1024UL,size-at);if(MemoryRead(selector,offset+at,chunk,n)!=(DWORD)n||!writeBytes(f,chunk,n))return 0;}return writeBytes(f,"\n",1);
}
static int writeMap(FILE*f,unsigned mapSel,unsigned pointerOffset,unsigned label,unsigned long size,HTASK task){
 unsigned ptr[2];GLOBALENTRY ge;HGLOBAL handle;char line[128];
 if(MemoryRead(mapSel,pointerOffset,ptr,4L)!=4L)return 0;
 handle=(HGLOBAL)LOWORD(GlobalHandle(ptr[1]));memset(&ge,0,sizeof(ge));ge.dwSize=sizeof(ge);
 if(!GlobalEntryHandle(&ge,handle)||ge.hOwner!=(HGLOBAL)task||!ptr[1]||!size||size>196602UL||(DWORD)ptr[0]+size>ge.dwBlockSize)return 0;
 if(GlobalHandleToSel(ge.hBlock)!=ptr[1])return 0;
 sprintf(line,"MAP %u %u %u %u %u %lu %lu\n",label,(unsigned)ge.hBlock,ptr[1],(unsigned)ge.hOwner,ptr[0],ge.dwBlockSize,size);
 return writeBytes(f,line,strlen(line))&&readRegion(f,ptr[1],ptr[0],size);
}
static int observe(const char*nonce){
 MODULEENTRY me;TASKENTRY te;GLOBALENTRY ge;FILE*f;unsigned segs[]={77,78,80};unsigned i,mapSel=0,stateSel=0,human=0,dimensions[7],selector;
 unsigned char before[316],after[316];char line[128],tail[64];DWORD ticks=GetTickCount(),total;int ok=1;
 sample(nonce);if(overflow||roots!=1||active!=root||GetWindowTask(active)!=gameTask)return 0;
 memset(&me,0,sizeof(me));me.dwSize=sizeof(me);if(!ModuleFindName(&me,"CIV2"))return 0;
 memset(&te,0,sizeof(te));te.dwSize=sizeof(te);if(!TaskFindHandle(&te,gameTask)||te.hModule!=me.hModule)return 0;
 memset(&ge,0,sizeof(ge));ge.dwSize=sizeof(ge);if(!GlobalEntryModule(&ge,me.hModule,78))return 0;
 stateSel=GlobalHandleToSel(ge.hBlock);if(MemoryRead(stateSel,0x8b66L,before,316L)!=316L)return 0;
 f=fopen("C:\\OBSRESP.BIN","wb");if(!f)return 0;for(i=0;i<128;i++)fputc(' ',f);outputSize=0;outputHash=2166136261UL;
 sprintf(line,"TREE %u\n",used);ok=writeBytes(f,line,strlen(line))&&writeBytes(f,body,used)&&writeBytes(f,"\n",1);
 for(i=0;i<3&&ok;i++){
  memset(&ge,0,sizeof(ge));ge.dwSize=sizeof(ge);
  if(!GlobalEntryModule(&ge,me.hModule,segs[i])||ge.hOwner!=(HGLOBAL)me.hModule||ge.wType!=GT_DATA||!ge.dwBlockSize||ge.dwBlockSize>65536UL){ok=0;break;}
  selector=GlobalHandleToSel(ge.hBlock);if(segs[i]==80)mapSel=selector;
  sprintf(line,"SEG %u %u %u %u %lu %u\n",segs[i],(unsigned)ge.hBlock,selector,ge.wType,ge.dwBlockSize,(unsigned)ge.hOwner);
  ok=writeBytes(f,line,strlen(line))&&readRegion(f,selector,0L,ge.dwBlockSize);
 }
 if(ok){
  if(!mapSel||MemoryRead(mapSel,0L,dimensions,14L)!=14L||MemoryRead(stateSel,0x8b81L,&human,1L)!=1L)ok=0;
  else if(human<1||human>7||!dimensions[2]||dimensions[2]>32767||dimensions[0]<8||dimensions[1]<8||(DWORD)dimensions[0]*dimensions[1]!=2UL*dimensions[2])ok=0;
  else ok=writeMap(f,mapSel,0x18,0,6UL*dimensions[2],gameTask)&&writeMap(f,mapSel,0x2c+4*human,human,dimensions[2],gameTask);
 }
 if(MemoryRead(stateSel,0x8b66L,after,316L)!=316L||memcmp(before,after,316)||active!=GetActiveWindow()||GetWindowTask(active)!=gameTask)ok=0;
 if(!ok||outputSize>500000UL){fclose(f);return 0;}
 sprintf(tail,"\nEND2 %s\n",nonce);fwrite(tail,1,strlen(tail),f);total=128+outputSize+strlen(tail);while(total++<524288UL)fputc(' ',f);
 sprintf(line,"C2OBS2 %s %lu %u %u %lu %08lx\n",nonce,ticks,(unsigned)me.hModule,(unsigned)gameTask,outputSize,outputHash);
 fseek(f,0,SEEK_SET);fwrite(line,1,strlen(line),f);fclose(f);return 1;
}
static void poll(void){FILE*f;char req[128],nonce[33];unsigned i,n;
 f=fopen("C:\\OBSREQ.TXT","rb");if(!f)return;n=fread(req,1,128,f);fclose(f);
 if(n!=128||memcmp(req,"C2OBS2 ",7)||req[39]!='\n')return;for(i=40;i<128;i++)if(req[i]!=' ')return;
 memcpy(nonce,req+7,32);nonce[32]=0;for(i=0;i<32;i++)if(!strchr("0123456789abcdef",nonce[i]))return;
 if(!strcmp(lastNonce,nonce))return;if(observe(nonce))strcpy(lastNonce,nonce);
}
LONG FAR PASCAL __export proc(HWND h,UINT msg,WPARAM w,LPARAM l){if(msg==WM_TIMER){poll();return 0;}if(msg==WM_DESTROY){KillTimer(h,1);PostQuitMessage(0);return 0;}return DefWindowProc(h,msg,w,l);}
int PASCAL WinMain(HINSTANCE inst,HINSTANCE prev,LPSTR cmd,int show){WNDCLASS wc;HWND h;MSG msg;instance=inst;memset(&wc,0,sizeof(wc));wc.lpfnWndProc=proc;wc.hInstance=inst;wc.lpszClassName="Civ2_ReadonlyObserver";if(!RegisterClass(&wc))return 2;h=CreateWindow(wc.lpszClassName,"",WS_POPUP,0,0,0,0,NULL,NULL,inst,NULL);if(!h)return 3;SetTimer(h,1,55,NULL);while(GetMessage(&msg,NULL,0,0)){TranslateMessage(&msg);DispatchMessage(&msg);}return 0;}
