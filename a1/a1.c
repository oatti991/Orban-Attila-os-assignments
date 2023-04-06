#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>

int listing(const char *path, const char *nameStartsWith, int sizeSmaller, int recursive)
{
    DIR *dir = NULL;
    struct dirent *entry = NULL;
    char fullPath[512];
    struct stat statbuf;


    dir = opendir(path);
    if(dir == NULL)
    {
        perror("Could not open directory");
        return -1;
    }

    while((entry = readdir(dir)) != NULL)
    {
        if(strcmp(entry->d_name, ".") !=0 && strcmp(entry->d_name, "..") != 0)
        {
            snprintf(fullPath, 512, "%s/%s", path, entry->d_name);
            if(lstat(fullPath, &statbuf) == 0)
            {
                if(nameStartsWith != NULL)
                {
                    if(strncmp(entry->d_name, nameStartsWith, strlen(nameStartsWith)) == 0)
                    {
                        if(sizeSmaller == -1 || (S_ISREG(statbuf.st_mode) && statbuf.st_size < sizeSmaller))
                        {
                            printf("%s/%s\n", path, entry->d_name);
                        }

                    }
                }
                else if(sizeSmaller != -1)
                {
                    if(S_ISREG(statbuf.st_mode) && statbuf.st_size < sizeSmaller)
                    {

                        printf("%s/%s\n", path, entry->d_name);
                    }
                }
                else
                {
                    printf("%s/%s\n", path, entry->d_name);
                }
                if(recursive == 1 && S_ISDIR(statbuf.st_mode))
                {
                    listing(fullPath, nameStartsWith, sizeSmaller, recursive);
                }
            }
        }
    }

    closedir(dir);
    return 0;
}



int main(int argc, char **argv)
{
    char* path = NULL;
    char* nameStartsWith = NULL;
    int sizeSmaller = -1;
    int recursive = 0;
    int argumentCnt = 2;
    if (argc >= 2)
    {
        if (strcmp(argv[1], "variant") == 0)
        {
            printf("81247\n");
        }
        else if (strcmp(argv[1], "list") == 0)
        {
            while(argumentCnt < argc)
            {
                if(strncmp(argv[argumentCnt], "name_starts_with=", strlen("name_starts_with=")) == 0)
                {
                    nameStartsWith = argv[argumentCnt] + strlen("name_starts_with=");
                }
                else if(strncmp(argv[argumentCnt], "size_smaller=", strlen("size_smaller=")) == 0)
                {

                    sizeSmaller = atoi(argv[argumentCnt] + strlen("size_smaller="));
                    //printf("%d", sizeSmaller);

                }
                else if(strncmp(argv[argumentCnt], "path=", strlen("path=")) == 0)
                {

                    path = argv[argumentCnt] + strlen("path=");
                }
                else if(strncmp(argv[argumentCnt], "recursive", strlen("recursive")) == 0)
                {
                    recursive = 1;
                }
                argumentCnt++;
            }
            if (path != NULL)
            {
                printf("SUCCESS\n");
                if(recursive == 1)
                {
                    listing(path, nameStartsWith,sizeSmaller,recursive);
                }
                else
                {
                    recursive = 0;
                    listing(path, nameStartsWith, sizeSmaller, recursive);
                }

            }
            else
            {
                printf("ERROR\n");
                printf("invalid directory path\n");
            }
        }
    }
    return 0;
}
