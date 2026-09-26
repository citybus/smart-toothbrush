#include "stdint.h"
#include "stdio.h"
#include "math.h"
  
#define ANCHOR8            
#define SIMSIM   
#define SUPPORTY                                                                                                                                                                                                                              
#define FACE_ROLL_HALF_NEG   0   /* roll < 0 (LL / RL half-planes) */
#define FACE_ROLL_HALF_POS   1   /* roll > 0 (LR / RR half-planes) */
#define FACE_ROLL_ZONE_UP    0
#define FACE_ROLL_ZONE_SIDE  1   /* LEFT for lr=0, RIGHT for lr=1 */
#define FACE_ROLL_ZONE_DOWN  2

static const short FaceRollBound[2][2][3] = {
    /* lr == 0 (left hand):  neg half-plane = LL- set; pos half-plane = LR- set */
    { { 50, 90, 150 },   /* HALF_NEG: UP=LL=50, SIDE=LLLEFT=90, DOWN=LL=150 */
      { 40, 90, 150 } }, /* HALF_POS: UP=LR=40, SIDE=LRLEFT=90, DOWN=LR=150 */
    /* lr == 1 (right hand): neg half-plane = RL- set; pos half-plane = RR- set */
    { { 40, 90, 150 },   /* HALF_NEG: UP=RL=40, SIDE=RLRIGHT=90, DOWN=RL=150 */
      { 50, 90, 150 } }  /* HALF_POS: UP=RR=50, SIDE=RRRIGHT=90, DOWN=RR=150 */
};
#define HYS_MARGIN          5    /* hysteresis margin around each roll boundary */
#define MID_ENTER_ROLL_MIN   -135.0f  /* arming band (entered near roll=-90) */
#define MID_ENTER_ROLL_MAX   -45.0f
#define MID_FACE13_ROLL_MIN  -90.0f   /* face 13 window */
#define MID_FACE13_ROLL_MAX  -0.0f
#define MID_FACE14_ROLL_MIN  0.0f     /* face 14 window */
#define MID_FACE14_ROLL_MAX  90.0f
#define MID_FACE15_ROLL_MIN  -180.0f  /* face 15 window */
#define MID_FACE15_ROLL_MAX  -90.0f
#define MID_FACE16_ROLL_MIN  90.0f    /* face 16 window */
#define MID_FACE16_ROLL_MAX  180.0f
#define WIN16_SIZE        16
#define WIN16_INV_SIZE    0.0625f            
#define TH                15
#define FACETH            30
#define THRESHHOLDYUP     45
#define ANCHOR8_HOLD_TIME 3.5
#define MIDDLE_THRESHOLD  30
#define ACCY_THRESHOLD    0.3
#define YYAW_THRESHOLD     6
#define FD_TIME           0.25
#define JUSTSUM_TIME      1.0

static inline void win16_update3_var(
    float *bx, float *by, float *bz,  /* per-axis ring buffers, length >= 16 */
    float  sum   [3],                 /* Σx, inout */
    float  sum_sq[3],                 /* Σx², inout */
    int   *idx, int *full,            /* ring cursor, and "window full" flag */
    float  x0, float x1, float x2,    /* new samples (X, Y, Z) */
    float *m0, float *m1, float *m2,  /* out: new means */
    float *s0, float *s1, float *s2   /* out: population stddev (0 if not full) */
) {
    const int i = *idx;
    if (*full) {
        const float o0 = bx[i], o1 = by[i], o2 = bz[i];
        sum   [0] -= o0; sum   [1] -= o1; sum   [2] -= o2;
        sum_sq[0] -= o0 * o0; sum_sq[1] -= o1 * o1; sum_sq[2] -= o2 * o2;
    }
    bx[i] = x0; by[i] = x1; bz[i] = x2;
    sum   [0] += x0; sum   [1] += x1; sum   [2] += x2;
    sum_sq[0] += x0 * x0; sum_sq[1] += x1 * x1; sum_sq[2] += x2 * x2;

    if (++(*idx) == WIN16_SIZE) {
        *full = 1;
        *idx  = 0;
    }

    *m0 = sum[0] * WIN16_INV_SIZE;
    *m1 = sum[1] * WIN16_INV_SIZE;
    *m2 = sum[2] * WIN16_INV_SIZE;

    if (*full) {
        float v0 = sum_sq[0] * WIN16_INV_SIZE - (*m0) * (*m0);
        float v1 = sum_sq[1] * WIN16_INV_SIZE - (*m1) * (*m1);
        float v2 = sum_sq[2] * WIN16_INV_SIZE - (*m2) * (*m2);
        if (v0 < 0.0f) v0 = 0.0f;
        if (v1 < 0.0f) v1 = 0.0f;
        if (v2 < 0.0f) v2 = 0.0f;
        *s0 = sqrtf(v0);
        *s1 = sqrtf(v1);
        *s2 = sqrtf(v2);
    } else {
        *s0 = 0.0f;
        *s1 = 0.0f;
        *s2 = 0.0f;
    }
}

static inline void win16_update3_mean(
    float *bx, float *by, float *bz,  /* per-axis ring buffers, length >= 16 */
    float  sum[3],                    /* Σx, inout */
    int   *idx, int *full,            /* ring cursor, and "window full" flag */
    float  x0, float x1, float x2,    /* new samples (X, Y, Z) */
    float *m0, float *m1, float *m2   /* out: new means */
) {
    const int i = *idx;
    if (*full) {
        sum[0] -= bx[i];
        sum[1] -= by[i];
        sum[2] -= bz[i];
    }
    bx[i] = x0; by[i] = x1; bz[i] = x2;
    sum[0] += x0; sum[1] += x1; sum[2] += x2;

    if (++(*idx) == WIN16_SIZE) {
        *full = 1;
        *idx  = 0;
    }

    *m0 = sum[0] * WIN16_INV_SIZE;
    *m1 = sum[1] * WIN16_INV_SIZE;
    *m2 = sum[2] * WIN16_INV_SIZE;
}

static inline void face_debounce(float dt,
                                 unsigned short face,
                                 float threshold,
                                 unsigned short *fd_flag,
                                 float          *fd_sum,
                                 unsigned short *newface)
{
    if (*fd_flag) {
        *fd_sum += dt;
        if (*fd_sum >= threshold) {
            *newface = face;
            *fd_flag   = 0;
        }
    } else {
        *fd_sum = 0.0f;
    }
}

static inline float angle_delta_deg(float a_new, float a_old)
{
    float d = a_new - a_old;
    while (d >  180.0f) d -= 360.0f;
    while (d < -180.0f) d += 360.0f;
    return d;
}

static inline float rampf(float x, float x0, float w)
{
    float t = (x - x0) / (2.0f * w);
    return t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
}

void setface(short face);   

static inline void valid_setface_debounce(short cur_valid)
{
    static short prev         = -1;  
    static int   cnt          = 0;   
    static int   ever_changed = 0;  
    static int   fired        = 0;   

    if (prev == -1) {
        prev = cur_valid;
        cnt  = 1;
        return;
    }

    if (cur_valid != prev) {
        ever_changed = 1;
        prev  = cur_valid;
        cnt   = 1;
        fired = 0;
    } else {
        cnt++;
    }

    if (ever_changed && (cnt >= 3) && !fired) {
        setface(cur_valid);
        fired = 1;
    }
}

static float q0 = 1.0f, q1 = 0.0f, q2 = 0.0f, q3 = 0.0f;
static float vx = 0.0f, vy = 0.0f, vz = 0.0f;
static float exInt = 0.0f, eyInt = 0.0f, ezInt = 0.0f;
static float ex = 0.0f, ey = 0.0f, ez = 0.0f;
static float yyaw = 0.0f;
float lastyyaw = 0.0f;
float platformy = 0.0f, platformyp = 0.0f;
float platformystore = 0.0f, platformypstore = 0.0f;
float anchory8sum1 = 0.0f;
float justsum = 0.0f;
float V1 = 0.0f,V2 = 0.0f,V3 = 0.0f,V4 = 0.0f,V5 = 0.0f,V6 = 0.0f,V7 = 0.0f,V8 = 0.0f;
float V9 = 0.0f,V10 = 0.0f,V11 = 0.0f,V12 = 0.0f,V13 = 0.0f,V14 = 0.0f,V15 = 0.0f,V16 = 0.0f;
float gyro[3],acc[3],force[3];
float gyro_off[3] = {0.0f},force_off[3] = {0.0f};
float delta_t = 0.0f;
float yaw = 0.0f,pitch = 0.0f,roll = 0.0f;
float norm;
float tempq0,tempq1,tempq2,tempq3;	
float q0q0,q0q1,q0q2,q0q3,q1q1,q1q2,q1q3,q2q2,q2q3,q3q3;  
float accxbuf[WIN16_SIZE] = {0.0f}, accybuf[WIN16_SIZE] = {0.0f}, acczbuf[WIN16_SIZE] = {0.0f};   
float accxsum = 0.0f, accysum = 0.0f, acczsum = 0.0f;
float accsum_sq[3] = {0.0f};          
float accxmean = 0.0f, accymean = 0.0f, acczmean = 0.0f;
float xstddev = 0.0f, ystddev = 0.0f, zstddev = 0.0f;
float gyroxbuf[WIN16_SIZE] = {0.0f}, gyroybuf[WIN16_SIZE] = {0.0f}, gyrozbuf[WIN16_SIZE] = {0.0f};  
float gyroxsum = 0.0f, gyroysum = 0.0f, gyrozsum = 0.0f;
float gyroxmean = 0.0f, gyroymean = 0.0f, gyrozmean = 0.0f;
float forceybuf[128] = {0.0f}, forcezbuf[128] = {0.0f};
float forceysum = 0.0f, forcezsum = 0.0f;
float forceymean = 0.0f, forcezmean = 0.0f, forceypmean = 0.0f;
float prob_dy     = 0.0f;  
float anchor8keeppp  = 0.0f, anchor8keep  = 0.0f, anchor8keepp  = 0.0f;
unsigned short valid = 0;
unsigned short anchory8flag1 = 0;
unsigned short faceflag = 0, faceflag3 = 0;
unsigned short middle_flag = 0;   
unsigned short temp999 = 999;
unsigned int deltatime = 0;
unsigned short lr = 0;
unsigned short newface = 1, oldface = 1, face = 1;
unsigned short ps = 0;

float invSqrt(float number) {
	long i;
	float x2, y;

	x2 = number * 0.5f;
	y = number;
	i = *(long *) &y;
	i = 0x5f3759df - (i >> 1); /*0x5f375a86 is better*/
	y = *(float *) &i;
	y = y * (1.5f - (x2 * y * y));
	y = y * (1.5f - (x2 * y * y));
	y = y * (1.5f - (x2 * y * y));
	return y;
}

void pre(void)
{
    static short acc_idx   = 0;   
    static short acc_full  = 0;   
    static short gf_idx    = 0;   
    static short gf_full   = 0;   

    {
        float sum[3]   = { accxsum,    accysum,    acczsum };
        float sumsq[3] = { accsum_sq[0], accsum_sq[1], accsum_sq[2] };
        int idx  = (int)acc_idx;
        int full = (int)acc_full;

        win16_update3_var(accxbuf, accybuf, acczbuf,
                          sum, sumsq, &idx, &full,
                          acc[0], acc[1], acc[2],
                          &accxmean, &accymean, &acczmean,
                          &xstddev,  &ystddev,  &zstddev);

        accxsum = sum[0]; accysum = sum[1]; acczsum = sum[2];
        accsum_sq[0] = sumsq[0]; accsum_sq[1] = sumsq[1]; accsum_sq[2] = sumsq[2];
        acc_idx  = (short)idx;
        acc_full = (short)full;
    }

    {
        const int i       = (int)gf_idx;
        const int is_full = (int)gf_full;

        if (is_full) {
            gyroxsum  -= gyroxbuf[i];
            gyroysum  -= gyroybuf[i];
            gyrozsum  -= gyrozbuf[i];
            forceysum -= forceybuf[i];
            forcezsum -= forcezbuf[i];
        }

        gyroxbuf[i] = gyro[0]; gyroxsum += gyro[0];
        gyroybuf[i] = gyro[1]; gyroysum += gyro[1];
        gyrozbuf[i] = gyro[2]; gyrozsum += gyro[2];
        forceybuf[i] = force[1]; forceysum += force[1];
        forcezbuf[i] = force[2]; forcezsum += force[2];

        gf_idx = (short)(i + 1);
        if (gf_idx == WIN16_SIZE) {
            gf_full = 1;
            gf_idx  = 0;
        }

        gyroxmean  = gyroxsum  * WIN16_INV_SIZE;
        gyroymean  = gyroysum  * WIN16_INV_SIZE;
        gyrozmean  = gyrozsum  * WIN16_INV_SIZE;
        forceymean = forceysum * WIN16_INV_SIZE;
        forcezmean = forcezsum * WIN16_INV_SIZE;
    }
    forceypmean = forceymean + 1.0f;
		
		if (ps == 0)
		{	
		force_off[1] = forceymean;

    if (acc[1] > ACCY_THRESHOLD)			
    {
		face = 2;newface = 2;lr = 1;
		}		
    if (acc[1] < -ACCY_THRESHOLD)			
    {
		face = 1;newface = 1;lr = 0;
		}		
		lastyyaw = yyaw;		
    temp999 = 0;	
		}
}

void attitude_update(float gx, float gy, float gz, float ax, float ay, float az, float t) {

	#ifdef SUPPORTY
	yyaw += gy * 180.0f / 3.14159265f * t;
  yyaw = (yyaw > 179.999f) ? -179.999f : (yyaw < -179.999f) ? 179.999f : yyaw;
		
  q0q0 = q0 * q0;
  q0q1 = q0 * q1;
  q0q2 = q0 * q2;
  q0q3 = q0 * q3;
  q1q1 = q1 * q1;
  q1q2 = q1 * q2;
  q1q3 = q1 * q3;
  q2q2 = q2 * q2;   
  q2q3 = q2 * q3;
  q3q3 = q3 * q3;  	
 
  norm = invSqrt(ax * ax + ay * ay + az * az);       
  ax = ax * norm;
  ay = ay * norm;
  az = az * norm;
	
  vx = 2 * (q1q3 - q0q2);
  vy = 2 * (q0q1 + q2q3);
  vz = q0q0 - q1q1 - q2q2 + q3q3;
  
  ex = (ay * vz - az * vy);
  ey = (az * vx - ax * vz);
  ez = (ax * vy - ay * vx);
	
if(ex != 0 && ey != 0 && ez != 0){
  exInt = exInt + ex * 0.01f * 0.5f * t;
  eyInt = eyInt + ey * 0.01f * 0.5f * t;	
  ezInt = ezInt + ez * 0.01f * 0.5f * t;

  gx = gx + 10.0f * ex + exInt;
  gy = gy + 10.0f * ey + eyInt;
  gz = gz + 10.0f * ez + ezInt;
  }
	
  tempq0 = q0 + (-q1 * gx - q2 * gy - q3 * gz)* 0.5f * t;
  tempq1 = q1 + (q0 * gx + q2 * gz - q3 * gy)* 0.5f * t;
  tempq2 = q2 + (q0 * gy - q1 * gz + q3 * gx)* 0.5f * t;
  tempq3 = q3 + (q0 * gz + q1 * gy - q2 * gx)* 0.5f * t;  

  norm = invSqrt(tempq0 * tempq0 + tempq1 * tempq1 + tempq2 * tempq2 + tempq3 * tempq3);
  q0 = tempq0 * norm;
  q1 = tempq1 * norm;
  q2 = tempq2 * norm;
  q3 = tempq3 * norm;
	
	yaw = (float)(atan2(2 * q1 * q2 + 2 * q0 * q3, -2 * q2 * q2 - 2 * q3 * q3 + 1) * 180.0f / 3.14159265f);
  pitch = (float)(-asin(-2 * q1 * q3 + 2 * q0 * q2) * 180 / 3.14159265f);
  roll = (float)(+atan2(2 * q2 * q3 + 2 * q0 * q1, -2 * q1 * q1 - 2 * q2 * q2 + 1) * 180.0f / 3.14159265f);
	#endif
	#ifndef SUPPORTY 
	pitch = (float)(atan(ax / fabs(az)) * 180.0f / 3.14159265f);//2 象限
	roll = (float)(atan2(ay, az) * 180.0f / 3.14159265f);	
	#endif
	roll = roll - 45.0f;
	if (roll <= -180.0f)
  roll = roll + 360.0f;		
}

void go(void) {

	 static unsigned short fd_flag = 0;
	 static float          fd_sum  = 0.0f;
	 	 		
   if (ps == 3) {
	  oldface = newface;	  	 		 
					    	
	#ifdef SUPPORTY 
	const float dy = angle_delta_deg(yyaw, lastyyaw);
	prob_dy = rampf(fabs(dy), 0.0f, (float)YYAW_THRESHOLD) * (dy >= 0.0f ? -1.0f : 1.0f);
    if (acc[1] > ACCY_THRESHOLD)
		{
		if ((dy > YYAW_THRESHOLD))	 		 
    { 	
			lr = 1;temp999 = 2;
    }			
	  if ((dy < -YYAW_THRESHOLD))	 		 
    { 		                                             
			lr = 0;temp999 = 1;
    }
	}	
			
	if (acc[1] < -ACCY_THRESHOLD) 
	{
		if ((dy > YYAW_THRESHOLD))		 
    { 	                                                 	
			lr = 0;temp999 = 1;
    }			
	  if ((dy < -YYAW_THRESHOLD))	 		 
    { 		
			lr = 1;temp999 = 2;
    }
	}	 
	#endif

 #ifdef ANCHOR8
   if (force[1] > anchor8keeppp)
	 {
		 anchor8keeppp = force[1];	 
		 anchor8keepp = anchor8keeppp;
	 }
   if (force[1] < anchor8keepp)
		 anchor8keepp = force[1];	 

	 if (fabs(force[1] - forceymean) < TH)
	   platformy = forceymean;	 
	 if (fabs(force[1] - forceypmean) < TH)
	   platformyp = forceypmean;	 
 
 if (((platformystore == platformy) || (platformypstore == platformyp)) && (((force[1] - platformy) >  FACETH) || ((force[1] - platformyp) >  FACETH)) && (faceflag == 0))
 { 
 faceflag = 1;
 }

 if (faceflag == 1)
	 faceflag3 = 1;

 if ((platformystore != platformy) && (platformypstore != platformyp))  
 {
 faceflag = 0;
 }
 
 platformystore = platformy;
 platformypstore = platformyp; 
 
	 if (((anchor8keeppp - platformy) > THRESHHOLDYUP))	 
	 {anchory8flag1 = 1;
	 }
	 if (anchory8flag1 == 1)
	 {anchory8sum1 = anchory8sum1 + delta_t;
	 }
	 if (anchory8sum1 > ANCHOR8_HOLD_TIME)
	 {
    anchory8flag1 = 0;
	  anchory8sum1 = 0.0f;			
		{
		if (acc[1] > 0.0f)				
    {
    valid = 1;
		}
		if (acc[1] < -0.0f)			
    {
    valid = 2;
		}		
	  }			
		
		if (faceflag3 == 1)
		{
			if (acc[1] > 0.0f)			
    {
    valid = 2;
		}
		if (acc[1] < -0.0f)			
    {
    valid = 1;
		}		
	  }
		anchor8keepp = 100;//low 2nd reset
		anchor8keeppp = -100;//high 2nd reset
		faceflag3 = 0;
	 }
	 valid_setface_debounce(valid);
 #endif

	 
			/* Face zone selection by roll angle.
			 *
			 * Historical 12 SURFACER macros have been collapsed into the
			 * FaceRollBound[hand][half-plane][zone] table.  For each hand the
			 * UP / SIDE / DOWN boundaries on the roll<0 half-plane (HALF_NEG)
			 * and roll>0 half-plane (HALF_POS) are loaded as locals once so
			 * every comparison below is trivial to audit.
			 *
			 * The 6 intervals per hand, with their shared endpoint hysteresis
			 * margin of +/- HYS_MARGIN around each boundary:
			 *   [ face 1/2 ] UP          : between -neg_UP and +pos_UP
			 *   [ face 4/10] pos SIDE/DOWN band : between  pos_SIDE+DR ... pos_DOWN-DR
			 *   [ face 10/]pos DOWN     : between  pos_DOWN+DR ... 180
			 *   [ face 3/9 ] neg SIDE/DOWN band : between -neg_SIDE-DR ... -neg_DOWN+DR
			 *   [ face 9/ ] neg DOWN     : between -180            ... -neg_DOWN-DR
			 *   [ face 6/12 ] mirror of the above on the opposite hand's SIDE zone.
			 */
			{
				const int h = (int)lr;
				const short upN = FaceRollBound[h][FACE_ROLL_HALF_NEG][FACE_ROLL_ZONE_UP];
				const short upP = FaceRollBound[h][FACE_ROLL_HALF_POS][FACE_ROLL_ZONE_UP];
				const short sdN = FaceRollBound[h][FACE_ROLL_HALF_NEG][FACE_ROLL_ZONE_SIDE];
				const short sdP = FaceRollBound[h][FACE_ROLL_HALF_POS][FACE_ROLL_ZONE_SIDE];
				const short dnN = FaceRollBound[h][FACE_ROLL_HALF_NEG][FACE_ROLL_ZONE_DOWN];
				const short dnP = FaceRollBound[h][FACE_ROLL_HALF_POS][FACE_ROLL_ZONE_DOWN];
				const short DR  = HYS_MARGIN;

				if (lr == 1) {
					if      ((roll <  (upP - DR)) && (roll >  (-upN + DR))) face = 2;
					else if ((roll <  (sdP - DR)) && (roll >  (upP + DR))) face = 4;
					else if ((roll < (-upN - DR)) && (roll >  (-sdN + DR))) face = 6;
					else if (((roll < 180) && (roll >  (dnP + DR))) ||
					         ((roll < (-dnN - DR)) && (roll > -180)))   face = 8;
					else if ((roll >  (sdP + DR)) && (roll <  (dnP - DR))) face = 10;
					else if ((roll > (-dnN + DR)) && (roll <  (-sdN - DR))) face = 12;
				} else {
					if      ((roll <  (upP - DR)) && (roll >  (-upN + DR))) face = 1;
					else if ((roll < (-upN - DR)) && (roll >  (-sdN + DR))) face = 3;
					else if ((roll <  (sdP - DR)) && (roll >  (upP + DR))) face = 5;
					else if (((roll < 180) && (roll >  (dnP + DR))) ||
					         ((roll < (-dnN - DR)) && (roll > -180)))   face = 7;
					else if ((roll > (-dnN + DR)) && (roll <  (-sdN - DR))) face = 9;
					else if ((roll >  (sdP + DR)) && (roll <  (dnP - DR))) face = 11;
				}
			}
			  
  if (((int)(pitch) <  MIDDLE_THRESHOLD) && ((int)(pitch) > -MIDDLE_THRESHOLD) &&
        (roll < MID_ENTER_ROLL_MAX) && (roll > MID_ENTER_ROLL_MIN))
	{
		 middle_flag = 1;
	}
	else if (((int)(pitch) < -MIDDLE_THRESHOLD * 1.2f) || ((int)(pitch) > MIDDLE_THRESHOLD * 1.2f))
	{
		 middle_flag = 0;
	}

	if (middle_flag == 1)
	{
		if      ((roll > MID_FACE13_ROLL_MIN) && (roll < MID_FACE13_ROLL_MAX))
		{ face = 13;}
		else if ((roll > MID_FACE15_ROLL_MIN) && (roll < MID_FACE15_ROLL_MAX))
		{ face = 15;}
		else if ((roll > MID_FACE14_ROLL_MIN) && (roll < MID_FACE14_ROLL_MAX))
		{ face = 14;}
		else if ((roll > MID_FACE16_ROLL_MIN) && (roll < MID_FACE16_ROLL_MAX))
		{ face = 16;}
	}

	 if (oldface != face)
		 fd_flag = 1;
	 face_debounce(delta_t, face, FD_TIME, &fd_flag, &fd_sum, &newface);	 
	 }  /* end if (ps == 3) */
	 justsum = justsum + delta_t;
	 if (justsum > JUSTSUM_TIME)
	 {
	  lastyyaw = yyaw;
    justsum = 0.0f;		 
	 }
}

#ifndef SIMSIM
extern float get_dt(void);
#endif
#ifdef SIMSIM
void update_deltatime(unsigned int time)
{
	deltatime = time;
}
void V1_V16(float *V)
{
	V[0] = V1;
	V[1] = V2;
	V[2] = V3;
	V[3] = V4;
	V[4] = V5;
	V[5] = V6;
	V[6] = V7;
	V[7] = V8;
	V[8] = V9;
	V[9] = V10;
	V[10] = V11;
	V[11] = V12;
	V[12] = V13;
	V[13] = V14;
	V[14] = V15;
	V[15] = V16;	
}

float get_dt(void)
{
	return(deltatime / 1000.0f);
}
#endif
				
void setface(short face)
{
	lr = face - 1;temp999 = temp999 + 10 * (lr == 0 ? 1 : 2);
	return;
}

void init(void)
{
  q0 = 1;
  q1 = 0;
  q2 = 0;
  q3 = 0;
  vx = 0;
	vy = 0;
	vz = 0;
  exInt = 0;
	eyInt = 0;
	ezInt = 0;
  ex = 0;
	ey = 0;
	ez = 0;	
}

void post(void)
{
  V1 = face;//delta_t * 1000;
  V2 = newface;
  V3 = yaw;
  V4 = lr * 100 + ps * 1; 
  V5 = pitch;
  V6 = roll;
  V7 = yyaw;
  V8 = lastyyaw;
  V9 = anchory8flag1;
  V10 = faceflag3;
  V11 = middle_flag;
  V12 = acc[1] * 10;
  V13 = 0;
  V14 = 0;
  V15 = 0;
  V16 = temp999;	
  temp999 = 0;		
}
	
short alg_toothbrush_update(float *accVal, float *gyroVal, short pressState, float *forceVal, short *area, short *area2, short *area3, short *para)	
{
	ps = pressState;
  gyro[0] = gyroVal[0];gyro[1] = gyroVal[1];gyro[2] = gyroVal[2];
  acc[0] = accVal[0];acc[1] = accVal[1];acc[2] = accVal[2];	
	force[0] = forceVal[0];force[1] = forceVal[1];force[2] = forceVal[2];	
	pre();	
	delta_t = get_dt();
	attitude_update(gyro[0] * 3.14159265f / 180.0f, gyro[1] * 3.14159265f / 180.0f, gyro[2] * 3.14159265f / 180.0f, acc[0], acc[1], acc[2], delta_t);
	go();
	post();	
  return newface;
}
