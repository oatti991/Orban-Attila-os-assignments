#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#define REQ_PIPE_NAME "REQ_PIPE_81247"
#define RESP_PIPE_NAME "RESP_PIPE_81247"
int VARIANT = 81247;

int main()
{
    int req_fd, resp_fd;
   
    if(mkfifo(RESP_PIPE_NAME, 0666) == -1) {
        perror("ERROR\ncannot create the response pipe");
        exit(1);
    }

   
    req_fd = open(REQ_PIPE_NAME, O_RDONLY);
    if(req_fd == -1)
    {
        perror("ERROR\ncannot open the request pipe");
        exit(1);
    }

   
    resp_fd = open(RESP_PIPE_NAME, O_WRONLY);
    if(resp_fd == -1)
    {
        perror("ERROR\ncannot open the response pipe");
        exit(1);
    }

    //char buff = 5;
    //write(req_fd, &buff, 1);
    write(resp_fd, "HELLO#", sizeof("HELLO#"));

    //printf("SUCCESS\n");


    close(req_fd);
    close(resp_fd);
    unlink(RESP_PIPE_NAME);
    return 0;
}
