clear;
%左外->右内->-左外->右外->左外->左内->右内->左内->右外->左内->左上咀嚼面->右上咀嚼面->右下咀嚼面->左下咀嚼面->中上外侧->中上内侧->中下外侧->中下内侧
datafile = '..\output\N1\20250515_102003_2.txt';
% readmatrix requires R2019a+; fall back to dlmread on older releases (R2018b)
if exist('readmatrix', 'file')
    D = readmatrix(datafile);
else
    D = dlmread(datafile, ',');
end
VER = D(:,1);  DAT = D(:,2);  DET = D(:,3);  R1 = D(:,4);
AX  = D(:,5);  AY  = D(:,6);  AZ  = D(:,7);
GX  = D(:,8);  GY  = D(:,9);  GZ  = D(:,10);
FX  = D(:,11); FY  = D(:,12); FZ  = D(:,13);
V1  = D(:,14); V2  = D(:,15); V3  = D(:,16); V4  = D(:,17);
V5  = D(:,18); V6  = D(:,19); V7  = D(:,20); V8  = D(:,21);
V9  = D(:,22); V10 = D(:,23); V11 = D(:,24); V12 = D(:,25);
V13 = D(:,26); V14 = D(:,27); V15 = D(:,28); V16 = D(:,29);
R2  = D(:,30); R3  = D(:,31); R4  = D(:,32); R5 = D(:,33);
R6  = D(:,34); R7  = D(:,35); T  = D(:,36);

VV = FY;

platform1(1,1) = VV(1);
platform1store = platform1(1,1);

platform1p(1,1) = VV(1);
platform1pstore = platform1p(1,1);

%%%%%%%%%%%%%
th = 4;
faceth = 5;
THRESHHOLDYUP = 41;
%%%%%%%%%%%%%

THRESHHOLDYUP3 = 100;
faceflag = 0;
faceflag3 = 0;
anchory8flag1 = 0;
kk = 0;

len = 128;
high(1,1) = VV(1);
low(1,1) = VV(1);

L=length(VV);
t=1:1:L;

winSum   = zeros(1, L);
winMean  = zeros(1, L);
winMeanP = zeros(1, L);

for i = 1 : L - len + 1%%%%
 winSum(i) = 0;
 for j = i : i + len - 1
  if (VV(j) > high(i,1))
  high(j,1) = VV(j);
  low(j,1) = VV(j);
  end
  if (VV(j) < low(i,1))
  low(j,1) = VV(j);
  end  
  winSum(i) = winSum(i) + VV(j);
  end
 if (i < L - len + 1)
 high(i + 1,1) = high(i,1);
 low(i + 1,1) = low(i,1);
 end 
 
 winMean(i + len - 1) = winSum(i) / len;
 winMeanP(i + len - 1) = winSum(i) / len + 1;

 if ((abs(VV(i) - winMean(i)) < th))
 platform1(i,1) = winMean(i);
 end
 if ((abs(VV(i) - winMeanP(i)) < th))
 platform1p(i,1) = winMeanP(i);
 end

 if (((platform1store == platform1(i,1)) || (platform1pstore == platform1p(i,1))) && (((VV(i) - platform1(i,1)) > faceth) || ((VV(i) - platform1p(i,1)) > faceth)) && (faceflag == 0))
 faceflag = 1;
  
 end

 if (faceflag == 1)
	 faceflag3 = 1; 
 end

 if ((platform1store ~= platform1(i,1)) && (platform1pstore ~= platform1p(i,1)))%%%    
 faceflag = 0;
 
 end%%%

 platform1store = platform1(i,1);
 platform1pstore = platform1p(i,1);
 
 if ((high(i,1) - platform1(i,1)) > THRESHHOLDYUP)
 	anchory8flag1 = 1;
 end
 
 if (anchory8flag1 == 1)
 kk = kk + 1;
 end
 
 if (kk == 150)
  anchory8flag1 = 0;
  faceflag3 = 0;
  kk = 0;
  high(i,1) = -THRESHHOLDYUP3;
  low(i,1) = THRESHHOLDYUP3;
 end

 if (i < L - len + 1)
 high(i + 1,1) = high(i,1);
 low(i + 1,1) = low(i,1);
 end 
  
 if (i < L - len + 1)
 platform1(i+1,1) = platform1(i);
 platform1p(i+1,1) = platform1p(i);
 end
 
 debug(i,1) = i;
 debug(i,2) = 0;
 debug(i,3) = 0;
 debug(i,4) = faceflag;
 debug(i,5) = high(i,1);
 debug(i,6) = low(i,1);
 debug(i,7) = 0;
 debug(i,8) = faceflag3;
 debug(i,9) = anchory8flag1; 
 
end%%%%

figure (101)
plot(t(1 : L - len + 1),FY(1 : L - len + 1),'g*');
hold on
plot(t(1 : L - len + 1),V2(1 : L - len + 1) * 10,'k*');
hold on
plot(t(1 : L - len + 1),V5(1 : L - len + 1) * 1,'r>');
hold on
plot(t(1 : L - len + 1),V6(1 : L - len + 1) * 1,'b>');
hold on
plot(t(1 : L - len + 1),V11(1 : L - len + 1) * -20,'y>');
hold on



% k     b    c    g     m        r   w     y
% black blue cyan green magnenta red white yellow
% .   *        X     o      +    s      d       p    v        ^        <        >        H
% dot asterisk cross circle plus square diamond star triangle triangle triangle triangle hexagram
% -          --          -.               :
% solid line dashed line dash dotted line dotted line
%legend('','');
%title('');
%xlabel('');
%ylabel('');
%zlabel('');

