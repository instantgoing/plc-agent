PROGRAM Main
VAR
    Start AT %IX0.0 : BOOL;
    Motor AT %QX0.0 : BOOL;
END_VAR
VAR
    Timer1 : TON;
END_VAR

Timer1(IN := Start, PT := T#10s);
Motor := Timer1.Q;
END_PROGRAM

CONFIGURATION Config0
    RESOURCE Res0 ON PLC
        TASK MainTask(INTERVAL := T#20ms, PRIORITY := 0);
        PROGRAM Inst0 WITH MainTask : Main;
    END_RESOURCE
END_CONFIGURATION
