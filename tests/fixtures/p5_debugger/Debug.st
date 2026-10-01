FUNCTION_BLOCK FB_Motor
VAR_INPUT
  Enable : BOOL;
END_VAR
VAR_OUTPUT
  Running : BOOL;
END_VAR
Running := Enable;
END_FUNCTION_BLOCK

PROGRAM MAIN
VAR
  Start AT %IX0.0 : BOOL;
  Stop AT %IX0.1 : BOOL;
  Fault AT %IX0.2 : BOOL;
  Motor AT %QX0.0 : BOOL;
END_VAR
VAR
  Latched : BOOL;
  MotorTimer : TON;
  Motor1 : FB_Motor;
  Motor2 : FB_Motor;
  Level : INT;
  Speed : REAL;
  Bench00, Bench01, Bench02, Bench03, Bench04, Bench05, Bench06, Bench07, Bench08, Bench09,
  Bench10, Bench11, Bench12, Bench13, Bench14, Bench15, Bench16, Bench17, Bench18, Bench19,
  Bench20, Bench21, Bench22, Bench23, Bench24, Bench25, Bench26, Bench27, Bench28, Bench29,
  Bench30, Bench31, Bench32, Bench33, Bench34, Bench35, Bench36, Bench37, Bench38, Bench39,
  Bench40, Bench41, Bench42, Bench43, Bench44, Bench45, Bench46, Bench47, Bench48, Bench49,
  Bench50, Bench51, Bench52, Bench53, Bench54, Bench55, Bench56, Bench57, Bench58, Bench59,
  Bench60, Bench61, Bench62, Bench63, Bench64, Bench65, Bench66, Bench67, Bench68, Bench69,
  Bench70, Bench71, Bench72, Bench73, Bench74, Bench75, Bench76, Bench77, Bench78, Bench79,
  Bench80, Bench81, Bench82, Bench83, Bench84, Bench85, Bench86, Bench87, Bench88, Bench89,
  Bench90, Bench91, Bench92, Bench93, Bench94, Bench95, Bench96, Bench97, Bench98, Bench99 : DINT;
END_VAR
MotorTimer(IN := Start, PT := T#5s);
Motor := Start AND NOT Stop AND NOT Fault AND NOT MotorTimer.Q;
Latched := (Latched OR Start) AND NOT Stop;
Motor1(Enable := Start);
Motor2(Enable := Stop);
Level := Level + 1;
Speed := 12.5;
END_PROGRAM

CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK MainTask(INTERVAL := T#20ms, PRIORITY := 0);
    PROGRAM Inst0 WITH MainTask : MAIN;
  END_RESOURCE
END_CONFIGURATION
