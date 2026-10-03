#include <stdint.h>
#ifndef BUILD_ID
#define BUILD_ID 0x4001
#endif
#define IO(off) (*(volatile uint32_t *)(0x10000000u + (off)))
#define ACC(off) (*(volatile uint32_t *)(0x20000000u + (off)))
#define MAX_N 1024u
#define MAX_PAYLOAD (4u + 4u * MAX_N)
#define RX_TIMEOUT 5000000u /* 100 ms at 50 MHz, measured between bytes. */
#define BARRIER() __asm__ volatile ("" ::: "memory")

enum { BAD_CRC=1, BAD_LENGTH, BAD_COMMAND, BAD_HEADER, RX_TIMED_OUT,
       UART_ERROR, SELFTEST_ERROR, ACCEL_ERROR };
static uint8_t payload[MAX_PAYLOAD];
static int16_t a[MAX_N], b[MAX_N];
static uint32_t selftest_mask, completed, receive_timeouts;
static const uint32_t crc_table[16] = {
    0x00000000,0x1db71064,0x3b6e20c8,0x26d930ac,
    0x76dc4190,0x6b6b51f4,0x4db26158,0x5005713c,
    0xedb88320,0xf00f9344,0xd6d6a3e8,0xcb61b38c,
    0x9b64c2b0,0x86d3d2d4,0xa00ae278,0xbdbdf21c
};
static uint32_t crc_byte(uint32_t crc, uint8_t value) {
    crc ^= value;
    crc = (crc >> 4) ^ crc_table[crc & 15u];
    return (crc >> 4) ^ crc_table[crc & 15u];
}
static uint16_t get16(const uint8_t *p) { return p[0] | ((uint16_t)p[1] << 8); }
static uint32_t get32(const uint8_t *p) { return get16(p) | ((uint32_t)get16(p+2) << 16); }
static void put16(uint8_t *p, uint16_t x) { p[0]=x; p[1]=x>>8; }
static void put32(uint8_t *p, uint32_t x) { put16(p,x); put16(p+2,x>>16); }
static void put64(uint8_t *p, uint64_t x) { put32(p,x); put32(p+4,x>>32); }
static uint32_t cycles(void) { BARRIER(); return IO(0x10); }
static void send_byte(uint8_t value) { IO(8)=value; }

/* Returns 1 for a byte, 0 for an inter-byte timeout, -1 for UART errors. */
static int receive_byte(uint8_t *value, int timed) {
    uint32_t start=cycles();
    for (;;) {
        uint32_t status=IO(0);
        if (status & 12u) return -1;
        if (status & 1u) { *value=(uint8_t)IO(4); return 1; }
        if (timed && (uint32_t)(cycles()-start) >= RX_TIMEOUT) return 0;
    }
}
static void drain_until_idle(void) {
    uint32_t last=cycles();
    IO(12)=1;
    for (;;) {
        uint32_t status=IO(0);
        if (status & 1u) { (void)IO(4); last=cycles(); }
        if (status & 12u) { IO(12)=1; last=cycles(); }
        if ((uint32_t)(cycles()-last) >= RX_TIMEOUT) return;
    }
}
static void response(uint8_t command, uint16_t seq, const uint8_t *body, uint16_t size) {
    uint8_t header[8] = {1,command,0,0,0,0,0,0};
    uint32_t crc=0xffffffffu;
    put16(header+2,seq); put16(header+4,size);
    send_byte('R'); send_byte('V'); send_byte('E'); send_byte('C');
    for (uint32_t i=0;i<8;i++) { send_byte(header[i]); crc=crc_byte(crc,header[i]); }
    for (uint32_t i=0;i<size;i++) { send_byte(body[i]); crc=crc_byte(crc,body[i]); }
    crc ^= 0xffffffffu;
    for (uint32_t i=0;i<4;i++) { send_byte((uint8_t)crc); crc >>= 8; }
}
static void error_response(uint16_t seq, uint32_t code, uint32_t detail) {
    uint8_t body[8]; put32(body,code); put32(body+4,detail);
    response(0xff,seq,body,sizeof body);
}

/* Normal -O2 RV32IM baseline: a signed 32-bit MUL, then a 64-bit sum. */
__attribute__((noinline)) static int64_t software_dot(const int16_t *pa, const int16_t *pb, uint32_t n) {
    BARRIER();
    int64_t total=0;
    for (uint32_t i=0;i<n;i++) {
        int32_t product=(int32_t)pa[i] * (int32_t)pb[i];
        total += product;
    }
    BARRIER();
    return total;
}
static int hardware_dot(uint32_t n, int64_t *result, uint32_t *core, uint32_t *status) {
    ACC(0)=2;
    for (uint32_t i=0;i<n;i++) {
        ACC(0x1000+4*i)=(uint16_t)a[i];
        ACC(0x2000+4*i)=(uint16_t)b[i];
    }
    ACC(8)=n; ACC(0)=1;
    uint32_t start=cycles();
    do {
        *status=ACC(4);
        if (*status & 4u) return 0;
        if ((uint32_t)(cycles()-start) >= 500000u) return 0;
    } while ((*status & 3u) != 2u);
    uint32_t low=ACC(0x10), high=ACC(0x14);
    *result=(int64_t)(((uint64_t)high<<32)|low);
    *core=ACC(0x18);
    return 1;
}
static uint32_t selftest(void) {
    static volatile uint32_t scratch[256];
    uint32_t mask=0, ok=1;
    for (uint32_t i=0;i<256;i++) scratch[i]=0x12345678u ^ i;
    for (uint32_t i=0;i<256;i++) if (scratch[i] != (0x12345678u ^ i)) ok=0;
    volatile uint8_t *bytes=(volatile uint8_t *)scratch;
    for (uint32_t i=0;i<1024;i++) bytes[i]=(uint8_t)(i ^ (i>>3));
    for (uint32_t i=0;i<1024;i++) if (bytes[i] != (uint8_t)(i ^ (i>>3))) ok=0;
    volatile uint16_t *halves=(volatile uint16_t *)scratch;
    for (uint32_t i=0;i<512;i++) halves[i]=(uint16_t)(0x8001u ^ i);
    for (uint32_t i=0;i<512;i++) if (halves[i] != (uint16_t)(0x8001u ^ i)) ok=0;
    if (ok) mask|=1;
    volatile int32_t x=-12345,y=321;
    volatile uint32_t u=4000000000u,v=3;
    if (x*y == -3962745 && x/y == -38 && x%y == -147 && u/v == 1333333333u && u%v == 1) mask|=2;
    const char *check="123456789";
    uint32_t crc=0xffffffffu;
    for (uint32_t i=0;i<9;i++) crc=crc_byte(crc,(uint8_t)check[i]);
    if ((crc ^ 0xffffffffu) == 0xcbf43926u) mask|=4;
    a[0]=1; a[1]=2; a[2]=3; b[0]=4; b[1]=5; b[2]=6;
    int64_t hw; uint32_t core,status;
    if (hardware_dot(3,&hw,&core,&status) && hw==32 && software_dot(a,b,3)==32 && core==5 &&
        ACC(0x1c)==0x444f5431u && IO(0x1c)==0x52563031u && IO(0x18)==50000000u) mask|=8;
    return mask;
}

#define WIN(off) (*(volatile uint32_t *)(0x20004000u + (off)))
#define NONE 0xffffffffu
static const int8_t target[64] = {
    1,1,-1,1,1,1,1,1,-1,-1,-1,1,1,1,-1,-1,1,1,-1,-1,-1,-1,1,1,
    -1,1,1,1,-1,-1,-1,1,-1,1,1,-1,-1,1,-1,1,-1,1,-1,-1,1,-1,1,-1,
    1,-1,-1,1,-1,-1,1,-1,-1,1,1,1,-1,-1,-1,1
};
struct peak { uint32_t detected, position, candidate; int32_t score; uint32_t energy; };
static struct peak sw_targets[4], hw_targets[4];
static uint32_t sw_count, hw_count;
static int32_t sw_scores[1024], hw_scores[1024];
static uint32_t sw_energies[1024], hw_energies[1024];
static uint32_t detections, trace_windows, trace_direct;
static struct peak empty_peak(void) {
    struct peak p={0,NONE,NONE,0,0}; return p;
}
static uint64_t squared(int32_t s) { return (uint64_t)((int64_t)s*s); }
static void consider(struct peak *p, uint32_t k, int32_t s, uint32_t e) {
    if (e && (p->candidate==NONE || squared(s)*p->energy > squared(p->score)*e)) {
        p->candidate=k; p->score=s; p->energy=e;
    }
}
static void finish_peak(struct peak *p) {
    p->detected=p->candidate!=NONE && 100u*squared(p->score) >= (uint64_t)3136u*p->energy;
    p->position=p->detected ? p->candidate : NONE;
}
__attribute__((noinline)) static struct peak software_scan(uint32_t n) {
    struct peak p=empty_peak();
    uint32_t energy=0;
    for (uint32_t i=0;i<64;i++) energy+=(int32_t)a[i]*a[i];
    for (uint32_t k=0;k<n-63;k++) {
        if (k) energy=energy-(int32_t)a[k-1]*a[k-1]+(int32_t)a[k+63]*a[k+63];
        int32_t s=0;
        // Exploit the same +/-1 template as RTL; no unnecessary software MUL.
        for (uint32_t i=0;i<64;i++) s+=target[i]<0 ? -(int32_t)a[k+i] : (int32_t)a[k+i];
        sw_scores[k]=s; sw_energies[k]=energy; consider(&p,k,s,energy);
    }
    finish_peak(&p); BARRIER(); return p;
}
static void software_multi(uint32_t n, const struct peak *first) {
    sw_count=0;
    for(uint32_t i=0;i<4;i++) sw_targets[i]=empty_peak();
    struct peak p=*first;
    while(p.detected && sw_count<4) {
        sw_targets[sw_count++]=p;
        if(sw_count==4) break;
        p=empty_peak();
        for(uint32_t k=0;k<n-63;k++) {
            uint32_t excluded=0;
            for(uint32_t j=0;j<sw_count;j++)
                if(k<sw_targets[j].position+64 && k+64>sw_targets[j].position) excluded=1;
            if(!excluded) consider(&p,k,sw_scores[k],sw_energies[k]);
        }
        finish_peak(&p);
    }
}
static int hardware_scan(uint32_t n, struct peak *p, uint32_t *metrics) {
    uint32_t start=cycles();
    WIN(0)=2; WIN(0x50)=0;
    uint32_t loading=WIN(0x14)==0;
    if (loading) for (uint32_t i=0;i<64;i++) WIN(0x2000+4*i)=(int32_t)target[i];
    metrics[0]=loading; metrics[1]=cycles()-start;
    start=cycles();
    for (uint32_t i=0;i<n;i++) WIN(0x1000+4*i)=(uint16_t)a[i];
    metrics[2]=cycles()-start;
    WIN(8)=n; WIN(0)=1;
    start=cycles();
    uint32_t status;
    do {
        status=WIN(4);
        if ((status&4u) || (uint32_t)(cycles()-start)>500000u) return 0;
    } while ((status&3u)!=2u);
    metrics[3]=WIN(0x18);
    *p=empty_peak();
    start=cycles();
    for (uint32_t k=0;k<n-63;k++) {
        WIN(0x20)=k;
        int32_t s=(int32_t)WIN(0x24); uint32_t e=WIN(0x28);
        hw_scores[k]=s; hw_energies[k]=e; consider(p,k,s,e);
    }
    finish_peak(p); metrics[4]=cycles()-start;
    return 1;
}
// Same complete task and integer decision, using the original DOT MMIO per window.
static int legacy_scan(uint32_t n, struct peak *p, uint32_t *metrics) {
    *p=empty_peak();
    uint32_t energy=0, core_total=0;
    for (uint32_t i=0;i<64;i++) energy+=(int32_t)a[i]*a[i];
    for (uint32_t k=0;k<n-63;k++) {
        if (k) energy=energy-(int32_t)a[k-1]*a[k-1]+(int32_t)a[k+63]*a[k+63];
        ACC(0)=2;
        for (uint32_t i=0;i<64;i++) {
            ACC(0x1000+4*i)=(uint16_t)a[k+i];
            ACC(0x2000+4*i)=(uint16_t)(int16_t)target[i];
        }
        ACC(8)=64; ACC(0)=1;
        uint32_t start=cycles(), status;
        do {
            status=ACC(4);
            if ((status&4u) || (uint32_t)(cycles()-start)>500000u) return 0;
        } while ((status&3u)!=2u);
        int32_t s=(int32_t)ACC(0x10);
        uint32_t high=ACC(0x14);
        if (high!=(s<0 ? 0xffffffffu : 0u)) return 0;
        core_total+=ACC(0x18);
        hw_scores[k]=s; hw_energies[k]=energy; consider(p,k,s,energy);
    }
    finish_peak(p);
    metrics[0]=1; metrics[1]=NONE; metrics[2]=NONE; metrics[3]=core_total; metrics[4]=NONE;
    return 1;
}

// Reads the FPGA's final exact peak; all-window validation is outside this timer.
static int hardware_peak(uint32_t n, struct peak *p, uint32_t *metrics, uint32_t multi) {
    uint32_t start=cycles();
    WIN(0)=2; WIN(0x50)=multi;
    uint32_t loading=WIN(0x14)==0;
    if (loading) for (uint32_t i=0;i<64;i++) WIN(0x2000+4*i)=(int32_t)target[i];
    metrics[0]=loading; metrics[1]=cycles()-start;
    start=cycles();
    for (uint32_t i=0;i<n;i++) WIN(0x1000+4*i)=(uint16_t)a[i];
    metrics[2]=cycles()-start;
    WIN(8)=n; WIN(0)=1;
    start=cycles();
    uint32_t status;
    do {
        status=WIN(4);
        if ((status&4u) || (uint32_t)(cycles()-start)>500000u) return 0;
    } while ((status&3u)!=2u);
    metrics[3]=WIN(0x18);
    start=cycles();
    p->detected=WIN(0x38); p->position=WIN(0x3c); p->candidate=WIN(0x40);
    p->score=(int32_t)WIN(0x44); p->energy=WIN(0x48);
    if(multi) {
        hw_count=WIN(0x54);
        for(uint32_t i=0;i<4;i++) {
            hw_targets[i]=empty_peak();
            hw_targets[i].position=WIN(0x60+12*i);
            hw_targets[i].score=(int32_t)WIN(0x64+12*i);
            hw_targets[i].energy=WIN(0x68+12*i);
        }
    }
    metrics[4]=cycles()-start;
    return 1;
}

static void capture_statistics(uint32_t n) {
    for (uint32_t k=0;k<n-63;k++) {
        WIN(0x20)=k;
        hw_scores[k]=(int32_t)WIN(0x24); hw_energies[k]=WIN(0x28);
    }
}


static uint32_t stats_crc(const int32_t *s, const uint32_t *e, uint32_t n) {
    uint32_t crc=0xffffffffu;
    for (uint32_t k=0;k<n;k++) {
        uint32_t words[2]={(uint32_t)s[k],e[k]};
        for (uint32_t j=0;j<2;j++) for (uint32_t i=0;i<4;i++) crc=crc_byte(crc,words[j]>>(8*i));
    }
    return crc^0xffffffffu;
}
static void put_peak(uint8_t *p, const struct peak *v) {
    put32(p,v->detected); put32(p+4,v->position); put32(p+8,v->candidate);
    put32(p+12,(uint32_t)v->score); put32(p+16,v->energy);
}
static void detection_command(uint8_t command, uint16_t seq, uint16_t size) {
    uint8_t body[520];
    if (command==4) {
        if (size!=4) { error_response(seq,BAD_LENGTH,size); return; }
        uint32_t k=get16(payload), count=get16(payload+2);
        if (!count || count>64 || k+count>trace_windows) { error_response(seq,BAD_LENGTH,k); return; }
        put16(body,k); put16(body+2,count);
        for (uint32_t i=0;i<count;i++) {
            if (trace_direct) {
                WIN(0x20)=k+i; put32(body+4+8*i,WIN(0x24)); put32(body+8+8*i,WIN(0x28));
            } else { put32(body+4+8*i,hw_scores[k+i]); put32(body+8+8*i,hw_energies[k+i]); }
        }
        response(0x84,seq,body,4+8*count); return;
    }
    if (size<4) { error_response(seq,BAD_LENGTH,size); return; }
    uint32_t n=get16(payload);
    if (n<64 || n>1024 || size!=4+2*n || get16(payload+2)) { error_response(seq,BAD_LENGTH,n); return; }
    if (selftest_mask!=15) { error_response(seq,SELFTEST_ERROR,selftest_mask); return; }
    for (uint32_t i=0;i<n;i++) {
        int32_t v=(int16_t)get16(payload+4+2*i);
        if (v < -2048 || v > 2047) { error_response(seq,9,i); return; }
        a[i]=(int16_t)v;
    }
    trace_windows=0;
    uint32_t start=cycles();
    struct peak sw=empty_peak();
    uint32_t sw_cycles=NONE;
    uint32_t fast=command==7 || command==9, multi=command>=8;
    if (!fast) { sw=software_scan(n); if(multi) software_multi(n,&sw); sw_cycles=cycles()-start; }
    else { sw.detected=NONE; sw.score=(int32_t)NONE; sw.energy=NONE; }
    struct peak hw; uint32_t metrics[5];
    start=cycles();
    int ok=command==5 ? legacy_scan(n,&hw,metrics) :
           command>=6 ? hardware_peak(n,&hw,metrics,multi) : hardware_scan(n,&hw,metrics);
    uint32_t hw_cycles=cycles()-start;
    if (!ok) { error_response(seq,ACCEL_ERROR,command==5 ? ACC(4) : WIN(4)); return; }
    trace_direct=fast;
    if (command==6 || command==8) capture_statistics(n);
    uint32_t mismatch=fast ? NONE : 0;
    if (!fast)
        for (uint32_t k=0;k<n-63;k++) if (sw_scores[k]!=hw_scores[k] || sw_energies[k]!=hw_energies[k]) mismatch++;
    detections++; trace_windows=n-63;
    put32(body,n); put32(body+4,n-63); put32(body+8,mismatch); put32(body+12,metrics[0]);
    put_peak(body+16,&sw); put_peak(body+36,&hw);
    put32(body+56,sw_cycles); put32(body+60,hw_cycles); put32(body+64,metrics[3]);
    put32(body+68,metrics[1]); put32(body+72,metrics[2]); put32(body+76,metrics[4]);
    put32(body+80,fast ? NONE : stats_crc(sw_scores,sw_energies,n-63));
    put32(body+84,fast ? NONE : stats_crc(hw_scores,hw_energies,n-63));
    put32(body+88,detections); put32(body+92,command==5 ? ACC(4) : WIN(4)); put32(body+96,BUILD_ID);
    put32(body+100,command==5 ? 64*(n-63) : WIN(0x2c));
    put32(body+104,command==5 ? 64*(n-63) : WIN(0x30));
    put32(body+108,command==5 ? n-63 : WIN(0x34));
    if(multi) {
        put32(body+112,fast ? NONE : sw_count); put32(body+116,hw_count);
        put32(body+120,4); put32(body+124,0);
        for(uint32_t i=0;i<4;i++) {
            put32(body+128+12*i,fast ? NONE : sw_targets[i].position);
            put32(body+132+12*i,fast ? NONE : (uint32_t)sw_targets[i].score);
            put32(body+136+12*i,fast ? NONE : sw_targets[i].energy);
            put32(body+176+12*i,hw_targets[i].position);
            put32(body+180+12*i,(uint32_t)hw_targets[i].score);
            put32(body+184+12*i,hw_targets[i].energy);
        }
    }
    response(command+0x80,seq,body,multi ? 224 : 112);
}

static void execute(uint8_t command, uint16_t seq, uint16_t size) {
    if (command==3 || command==4 || command==5 || command==6 || command==7 || command==8 || command==9) { detection_command(command,seq,size); return; }
    uint8_t body[40];
    if (command==1) {
        if (size) { error_response(seq,BAD_LENGTH,size); return; }
        put32(body,BUILD_ID); put32(body+4,IO(0x18)); put32(body+8,IO(0x1c));
        put32(body+12,ACC(0x1c)); put32(body+16,MAX_N); put32(body+20,selftest_mask);
        put32(body+24,completed); put32(body+28,receive_timeouts);
        response(0x81,seq,body,32); return;
    }
    if (command!=2) { error_response(seq,BAD_COMMAND,command); return; }
    if (size<4) { error_response(seq,BAD_LENGTH,size); return; }
    uint32_t n=get16(payload);
    if (n<1 || n>MAX_N || size != 4+4*n || get16(payload+2)) {
        error_response(seq,BAD_LENGTH,n); return;
    }
    if (selftest_mask!=15) { error_response(seq,SELFTEST_ERROR,selftest_mask); return; }
    for (uint32_t i=0;i<n;i++) {
        a[i]=(int16_t)get16(payload+4+4*i); b[i]=(int16_t)get16(payload+6+4*i);
    }
    uint32_t start=cycles();
    int64_t sw=software_dot(a,b,n);
    uint32_t sw_cycles=cycles()-start;
    int64_t hw; uint32_t core,status;
    start=cycles();
    int ok=hardware_dot(n,&hw,&core,&status);
    uint32_t total_cycles=cycles()-start;
    if (!ok) { error_response(seq,ACCEL_ERROR,status); return; }
    completed++;
    put16(body,n); put16(body+2,sw==hw ? 0 : 1);
    put64(body+4,(uint64_t)sw); put64(body+12,(uint64_t)hw);
    put32(body+20,sw_cycles); put32(body+24,total_cycles); put32(body+28,core);
    put32(body+32,status); put32(body+36,completed);
    response(0x82,seq,body,sizeof body);
}

int main(void) {
    selftest_mask=selftest();
    const uint8_t magic[4]={'R','V','E','C'};
    uint32_t matched=0;
    for (;;) {
        uint8_t value;
        int got=receive_byte(&value,matched!=0);
        if (got<0) { drain_until_idle(); error_response(0,UART_ERROR,0); matched=0; continue; }
        if (!got) { matched=0; continue; }
        if (value==magic[matched]) matched++;
        else matched=(value==magic[0]);
        if (matched!=4) continue;
        matched=0;
        uint8_t header[8]={0}, tail[4];
        uint32_t crc=0xffffffffu, count=0;
        uint16_t seq=0,size=0;
        for (;count<8;count++) {
            got=receive_byte(&header[count],1); if (got!=1) break;
            crc=crc_byte(crc,header[count]);
        }
        if (count>=4) seq=get16(header+2);
        if (got==1) {
            size=get16(header+4);
            if (size>MAX_PAYLOAD) {
                drain_until_idle(); error_response(seq,BAD_LENGTH,size); continue;
            }
            for (count=0;count<size;count++) {
                got=receive_byte(&payload[count],1); if (got!=1) break;
                crc=crc_byte(crc,payload[count]);
            }
        }
        if (got==1) for (count=0;count<4;count++) {
            got=receive_byte(&tail[count],1); if (got!=1) break;
        }
        if (got!=1) {
            if (!got) { receive_timeouts++; error_response(seq,RX_TIMED_OUT,0); }
            else { drain_until_idle(); error_response(seq,UART_ERROR,0); }
        } else if ((crc ^ 0xffffffffu)!=get32(tail)) {
            error_response(seq,BAD_CRC,0);
        } else if (header[0]!=1 || get16(header+6)) {
            error_response(seq,BAD_HEADER,0);
        } else execute(header[1],seq,size);
    }
}
