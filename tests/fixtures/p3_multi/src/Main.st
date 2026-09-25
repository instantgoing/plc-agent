PROGRAM MAIN
VAR
    StartPB AT %IX0.0 : BOOL;
    StopPB AT %IX0.1 : BOOL;
    FaultPB AT %IX0.2 : BOOL;
    Motor AT %QX0.0 : BOOL;
    AlarmOutput AT %QX0.1 : BOOL;
    MotorController : FB_Motor;
    AlarmController : FB_Alarm;
    Scaled : REAL;
END_VAR
MotorController(Start := StartPB, Stop := StopPB);
AlarmController(Trip := FaultPB);
Scaled := FC_Scale(1.0);
Motor := MotorController.Running AND SystemReady;
AlarmOutput := AlarmController.Active;
END_PROGRAM
