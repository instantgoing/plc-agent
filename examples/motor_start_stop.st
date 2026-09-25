PROGRAM Main
VAR
    Start AT %IX0.0 : BOOL;
    Stop AT %IX0.1 : BOOL;
    Motor AT %QX0.0 : BOOL;
END_VAR
VAR
    StartEdge : R_TRIG;
    RunTimer : TON;
    Running : BOOL := FALSE;
END_VAR

StartEdge(CLK := Start);
IF Stop THEN
    Running := FALSE;
ELSIF StartEdge.Q AND NOT Running THEN
    Running := TRUE;
END_IF;

RunTimer(IN := Running, PT := T#10s);
IF RunTimer.Q THEN
    Running := FALSE;
END_IF;
Motor := Running;
END_PROGRAM

CONFIGURATION Config0
    RESOURCE Res0 ON PLC
        TASK MainTask(INTERVAL := T#20ms, PRIORITY := 0);
        PROGRAM Inst0 WITH MainTask : Main;
    END_RESOURCE
END_CONFIGURATION
