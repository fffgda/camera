import cv2
import operator
import cvzone
from ultralytics import YOLO


cap=cv2.VideoCapture(0)
width=int(cap.get(3))
marge=70
facemodel = YOLO('yolov8n.pt')


while True:
    ret, frame=cap.read()
    tab_face=[]
    tickmark=cv2.getTickCount()
    
    face_result = facemodel.predict(frame,conf = 0.40)
    for info in face_result:
        parameters = info.boxes
        for box in parameters:
            x1, y1, x2, y2 = box.xyxy[0]
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            h,w = y2-y1,x2-x1
            cvzone.cornerRect(frame,[x1,y1,w,h],l=9,rt=3)
    if cv2.waitKey(1)&0xFF==ord('q'):
        break
    fps=cv2.getTickFrequency()/(cv2.getTickCount()-tickmark)
    
    cv2.putText(frame, "FPS: {:05.2f}".format(fps), (10, 30), cv2.FONT_HERSHEY_PLAIN, 2, (255, 0, 0), 2)
    cv2.imshow('video', frame)
    
    
cap.release()
cv2.destroyAllWindows()