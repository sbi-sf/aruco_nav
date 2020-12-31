#!/usr/bin/env python
import rospy
import message_filters
from sensor_msgs.msg import Image as msg_Image
from cv_bridge import CvBridge, CvBridgeError
import cv2
import cv2.aruco as aruco 
import numpy as np
import sys
import os
from std_msgs.msg import Bool
from robot_nav.msg import Marker
import math


class ImageListener:
	
    def __init__(self, depth_topic,color_topic=None,robot_width=1200):
        self.depth_topic = depth_topic
        self.color_topic = color_topic
        self.robot_width = robot_width
        self.threshold = 1000

        self.aruco_dict = aruco.Dictionary_get(aruco.DICT_4X4_50)
        self.aruco_params = aruco.DetectorParameters_create()

        
        self.bridge = CvBridge()
        self.depth_sub = message_filters.Subscriber(depth_topic, msg_Image)
        self.color_sub = message_filters.Subscriber(color_topic, msg_Image)
        self.sync = message_filters.TimeSynchronizer([self.depth_sub,self.color_sub],1)
        self.sync.registerCallback(self.imagesCallback)
        self.VISUALIZE= False
        self.log_info = False
        self.image_pub = rospy.Publisher('/mask/image',msg_Image,queue_size=1)
        self.obstacle_pub = rospy.Publisher('/ria/odom/obstacle',Bool,queue_size=1)
        self.marker_pub = rospy.Publisher('/ria/odom/marker', Marker, queue_size=1)
        rospy.loginfo("Initialized Listener")
        rospy.loginfo("Visualization: {}".format(self.VISUALIZE))
        rospy.loginfo("Info Logging: {}".format(self.log_info))
        self.mask_image = None
        self.marker_msg = Marker()
        self.marker_found = False
        self.startedObstacleDetection = False
        self.startedMarkerDetection = False

        self.cv_color_image=None
        self.cv_depth_image=None

        self.new_image=False

    def startObstacleDetection(self):
        if self.startedObstacleDetection:
            rospy.logwarn("Multiple attempts to strat thread for obstacle detection. Ignoring...")
            return False
        self.startedObstacleDetection = True
        rospy.loginfo("Obstacle Detection started")
        return True

    def startMarkerDetection(self):
        if self.startedMarkerDetection:
            rospy.logwarn("Multiple attempts to strat thread for marker detection. Ignoring...")
            return False
        self.startedMarkerDetection = True
        rospy.loginfo("Marker Detection started")
        return True


    def stopAll(self):
        self.startedObstacleDetection=False
        self.startedMarkerDetection=False



    def detectObstacle(self):
        if self.startedObstacleDetection:
                center_distance = self.cv_depth_image[self.mid[0],self.mid[1]]
                row,col = np.where(self.cv_depth_image<self.threshold)
                points = np.vstack((row,col)).T

                try:
                    right_limit = int(340+(485*((self.robot_width/2.0)/center_distance)))
                    left_limit = int(340-(485*((self.robot_width/2.0)/center_distance)))
                    if right_limit>=640:
                        right_limit=639
                    if left_limit<0:
                        left_limit=0
                except OverflowError as e:
                    rospy.logwarn(e)
                    right_limit=self.image_width-1
                    left_limit = 0

                left = points>=(0,left_limit)
                right = points<=(self.image_height,right_limit)
                total_points = np.logical_and(left,right)
                population = total_points.sum()-len(total_points)
                density = float(population)/float(self.image_height*(right_limit-left_limit))


                if self.VISUALIZE:
                    
                    #center
                    self.mask_image[self.mid[1]-20:self.mid[1]+20,self.mid[0]]=0
                    self.mask_image[self.mid[1],self.mid[0]-20:self.mid[0]+20]=0

                    #distance coloring
                    self.mask_image[row,col,0]=128

                    #left axis
                    self.mask_image[:,0:left_limit,1]=150
                    self.mask_image[:,left_limit]=255

                    #right axis
                    self.mask_image[:,right_limit:,1]=150
                    self.mask_image[:,right_limit]=255

                    #info box
                    self.mask_image[25:130,5]=255
                    self.mask_image[25:130,150]=255
                    self.mask_image[25,5:150]=255
                    self.mask_image[130,5:150]=255
                    
                    font=cv2.FONT_HERSHEY_TRIPLEX
                    fontScale = 0.32
                    thickness = 1

                    range_org = (10,45)
                    density_org = (10,105)
                    fov_org =(10,87)
                    r_width_org = (10,65)
                    obs_org = (10,125)
                    center_org=(self.mid[0]+15,self.mid[1]+15)

                    white=(255,255,255)
                    yellow=(255,255,0)
                    
                    color=white
                    if density>0.039:
                        obs_color=(255,0,0)
                    else:
                        obs_color=(0,255,0)
                    
                    range_str = "Threshold: {:.2f}m".format(self.threshold/1000.0)
                    r_width_str = "R_width: {:.2f}m".format(self.robot_width/1000.0)
                    obs_str = "Obstacle: "+str(density>0.039) 
                    density_str = "Density: {:.2f}%".format(density*100.0)
                    center_str = "{:.2f}m".format(center_distance/1000.0)  
                    fov_str = "FOV: {} [{:.2f}%]".format((right_limit-left_limit),100*float(right_limit-left_limit)/float(self.image_width))  
                    
                    self.mask_image = cv2.putText(self.mask_image,obs_str,obs_org,font,fontScale,obs_color,thickness,cv2.LINE_AA)
                    self.mask_image = cv2.putText(self.mask_image,range_str,range_org,font,fontScale,yellow,thickness,cv2.LINE_AA)
                    self.mask_image = cv2.putText(self.mask_image,center_str,center_org,font,fontScale,color,thickness,cv2.LINE_AA)
                    self.mask_image = cv2.putText(self.mask_image,r_width_str,r_width_org,font,fontScale,yellow,thickness,cv2.LINE_AA)


                if self.log_info:
                    rospy.loginfo("[DENSITY]:{} [Obstacle]:{} |Center:{}".format(density,density>0.039,center_distance))
                if density>0.039:
                    self.obstacle_pub.publish(True)
                else:
                    self.obstacle_pub.publish(False)


    def detectMarker(self):

        if self.startedMarkerDetection:
            if self.new_image:
                frame = self.cv_color_image
                frame_center_x = self.mid[0]
                _distance=0.0
                try:
                    gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                    corners,ids,rejects = aruco.detectMarkers(gray,self.aruco_dict,parameters=self.aruco_params)
                except:
                    rospy.logwarn("Error Reading Image, Is the topic being published?")
                    return None
            
                if corners:
                    self.marker_found = True
                    if self.log_info:
                        rospy.loginfo("Found Marker(s):"+str(ids.tolist()))               
                    _b = corners[0][0][3][1]-corners[0][0][0][1]
                    _a = corners[0][0][2][1]-corners[0][0][1][1]
                    _h = float(((corners[0][0][1][0]-corners[0][0][0][0])+(corners[0][0][2][0]-corners[0][0][3][0]))/2.0)

                    center_y = int((corners[0][0][3][1]-corners[0][0][0][1])/2 + corners[0][0][0][1])
                    delta_x = (((_b+2.0*_a)/(3.0*(_a+_b)))*_h)
                    center_x = int(delta_x+(corners[0][0][0][0]+corners[0][0][3][0])/2.0)
                    if _b > _a:
                    	_theta = -1.0
                    else:
                        _theta = 1.0
                    try:
                        _theta = _theta*math.acos(float(_h)/float(_b))
                        _theta = math.degrees(_theta)
                        if self.log_info:
                            rospy.loginfo("B:{},H:{},Theta:{}deg".format(_b,_h,_theta))
                        _distance = float(self.cv_depth_image[center_x,center_y])/1000.0  
                        self.marker_msg.id = ids[0][0]
                        self.marker_msg.distance = _distance
                        self.marker_msg.theta = _theta
                        self.marker_msg.aligned = (abs(center_x-frame_center_x)<abs(_h))
                    except ValueError:
                        rospy.logwarn("Error Calculating theta with values {},{}".format(_h,_b))
                    except ZeroDivisionError:
                        rospy.logwarn("Zero Divison Error")
                    except IndexError as e:
                        rospy.logwarn("Index Out of Bounds: {}".format(e))

                    if self.VISUALIZE:
                        font=cv2.FONT_HERSHEY_TRIPLEX
                        fontScale = 0.32
                        thickness = 1
                        yellow=(255,255,0)
                        aruco.drawDetectedMarkers(frame,corners)
                        frame = cv2.putText(frame,str(_distance),(int(center_x),int(center_y)-5),font,fontScale,yellow,thickness,cv2.LINE_AA)
                        frame = cv2.putText(frame,"{:.2f}deg".format(_theta),(int(center_x),int(center_y)-20),font,fontScale,(255,255,255),thickness,cv2.LINE_AA)
                        frame = cv2.putText(frame,str(ids[0]),(int(corners[0][0][3][0]),5+int(corners[0][0][3][1])),font,fontScale,(255,255,255),thickness,cv2.LINE_AA)
                        self.mask_image = frame
                        
                else:
                    rospy.logwarn("Markers not found")
                    self.mask_image = frame
                    self.marker_found = False
                self.new_image=False


    def publish_image(self):
        try:
            if self.VISUALIZE:
                self.image_pub.publish(self.bridge.cv2_to_imgmsg(self.mask_image,"rgb8"))
            #rospy.loginfo("Visualization Image published")
        except TypeError as e:
            rospy.logwarn("No Inference Image to publish")
        except CvBridgeError as e:
            rospy.logerr(e)
   
    def publish_marker(self):
        if self.marker_found:
            self.marker_pub.publish(self.marker_msg)
            if self.log_info:
                rospy.loginfo(marker_msg)


    def imagesCallback(self,depth_image,color_image):
        try:
            self.cv_color_image = self.bridge.imgmsg_to_cv2(color_image,color_image.encoding)
            self.cv_depth_image = self.bridge.imgmsg_to_cv2(depth_image,depth_image.encoding)
            self.mid = (color_image.width/2,color_image.height/2)
            self.image_width = color_image.width
            self.image_height = color_image.height
#            rospy.loginfo("Image Recieved")
            self.new_image = True
            #self.detectObstacle()
            #self.detectMarker()
            
        except CvBridgeError as e:
            print(e)
            return

def main():
    color_topic = '/camera/color/image_raw'
    depth_topic = '/camera/aligned_depth_to_color/image_raw'
    listener = ImageListener(depth_topic,color_topic)
    listener.startMarkerDetection()
    listener.startObstacleDetection()
    rate = rospy.Rate(15)
    try:
        while not rospy.is_shutdown():
            if listener.new_image:
                listener.detectMarker()
                listener.detectObstacle()
                listener.publish_image()
                listener.publish_marker()
            else:
                rospy.logwarn("Waiting for synchronized depth image")
            rate.sleep()
            

    except KeyboardInterrupt:
        listener.stopAll()
        rospy.loginfo("Stopping Node")
        print("Killing All Threads")
        exit()
if __name__ == '__main__':
    node_name = os.path.basename(sys.argv[0]).split('.')[0]
    rospy.init_node(node_name)
    main()
