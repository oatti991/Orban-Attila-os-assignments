#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>

char MAGIC[] ="Yie8";


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


int parsing(const char* path)
{

    char last_char[strlen(MAGIC) + 1];
    off_t last_char_pos;
    ssize_t b_read;

    int fd = open(path, O_RDONLY);
    if(fd == -1)
    {
        perror("Cannot open file");
        return -1;
    }

    last_char_pos = lseek(fd, -strlen(MAGIC), SEEK_END);
    if(last_char_pos == -1)
    {
        perror("Cannot seek to the end");
        close(fd);
        return -1;
    }

    b_read = read(fd, last_char, strlen(MAGIC));
    if(b_read == -1)
    {
        perror("Cannot read the last chars");
        close(fd);
        return -1;
    }

    last_char[strlen(MAGIC)] = '\0';
    if(strcmp(last_char, MAGIC) == 0)
    {
        printf("SUCCESS\n%s\n", last_char);

    }
    char header_size[2];
    off_t header_pos = lseek(fd, last_char_pos - 2, SEEK_SET);
    if(header_pos == -1)
    {
        perror("Cannot seek to header position");
        close(fd);
        return -1;
    }

    b_read = read(fd, header_size, 2);
    if(b_read == -1)
    {
        perror("Cannot read header size");
        close(fd);
        return -1;
    }


    char sect_size[4];
    off_t sect_size_pos = lseek(fd, last_char_pos - 2 - sizeof(int), SEEK_SET);
    if(sect_size_pos == -1)
    {
        perror("Cannot seek to section size position");
        close(fd);
        return -1;
    }

    b_read = read(fd, sect_size, sizeof(int));
    if(b_read == -1)
    {
        perror("Cannot read section size");
        close(fd);
        return -1;
    }

    // Read the section offset
    char sect_offset[4];
    off_t sect_offset_pos = lseek(fd, sect_size_pos - sizeof(int), SEEK_SET);
    if(sect_offset_pos == -1)
    {
        perror("Cannot seek to section offset position");
        close(fd);
        return -1;
    }

    b_read = read(fd, sect_offset, sizeof(int));
    if(b_read == -1)
    {
        perror("Cannot read section offset");
        close(fd);
        return -1;
    }

// Read the section type
    char sect_type[4];
    off_t sect_type_pos = lseek(fd, sect_offset_pos - sizeof(int), SEEK_SET);
    if(sect_type_pos == -1)
    {
        perror("Cannot seek to section type position");
        close(fd);
        return -1;
    }

    b_read = read(fd, sect_type, sizeof(int));
    if(b_read == -1)
    {
        perror("Cannot read section type");
        close(fd);
        return -1;
    }

    char sect_name[12]; // 11 characters for the name and 1 null character at the end
    off_t sect_name_pos = lseek(fd, sect_type_pos - 11, SEEK_SET);
    if(sect_name_pos == -1)
    {
        perror("Cannot seek to section name position");
        close(fd);
        return -1;
    }

    b_read = read(fd, sect_name, 11);
    if(b_read == -1)
    {
        perror("Cannot read section name");
        close(fd);
        return -1;
    }

    sect_name[11] = '\0'; // Add null character at the end to terminate the string


    // Read the number of sections

    char no_of_sections[2];
    off_t no_of_sections_pos = lseek(fd,  sect_name_pos - 1, SEEK_SET);
    if(no_of_sections_pos == -1)
    {
        perror("Cannot seek to the number of sections position");
        close(fd);
        return -1;
    }

    b_read = read(fd, no_of_sections, 1);
    if(b_read == -1)
    {
        perror("Cannot read the number of sections");
        close(fd);
        return -1;
    }

    no_of_sections[1] = '\0'; // Add null character at the end to terminate the string


    printf("Number of sections: %d\n", (int)*no_of_sections);

// Read the sizes and offsets of all sections
    for(int i = 0; i <(int) *no_of_sections; i++)
    {
        char sect_size[4];
        off_t sect_size_pos = lseek(fd, no_of_sections_pos - sizeof(int) - (i + 1) * 8, SEEK_SET);
        if(sect_size_pos == -1)
        {
            perror("Cannot seek to section size position");
            close(fd);
            return -1;
        }

        b_read = read(fd, sect_size, sizeof(int));
        if(b_read == -1)
        {
            perror("Cannot read section size");
            close(fd);
            return -1;
        }

        char sect_offset[4];
        off_t sect_offset_pos = lseek(fd, sect_size_pos - sizeof(int), SEEK_SET);
        if(sect_offset_pos == -1)
        {
            perror("Cannot seek to section offset position");
            close(fd);
            return -1;
        }

        b_read = read(fd, sect_offset, sizeof(int));
        if(b_read == -1)
        {
            perror("Cannot read section offset");
            close(fd);
            return -1;
        }

        int sect_size_value = *(int*)sect_size;
        int sect_offset_value = *(int*)sect_offset;

        printf("Section %d:\n", i + 1);
        printf("Size: %d\n", sect_size_value);
        printf("Offset: %d\n", sect_offset_value);
    }

    close(fd);
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
        else if(strcmp(argv[1], "parse") == 0)
        {
            if(strncmp(argv[argumentCnt], "path=", strlen("path=")) == 0)
            {
                path = argv[2] + strlen("path=");
                parsing(path);
            }
        }

    }
    return 0;
}
